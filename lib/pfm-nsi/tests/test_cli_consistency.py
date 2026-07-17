import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np

from pfm_nsi import cli
from pfm_nsi.reliability import conditional_reliability_from_nsi


def _fake_qc(mean_bias: bool = True):
    r2 = np.array([0.1, 0.2, 0.9], dtype=float) if mean_bias else np.array([0.2, 0.2, 0.2], dtype=float)
    return {
        "NSI": {
            "MedianScore": float(np.nanmedian(r2)),
            "Ridge": {"Lambda10": {"R2": r2}},
        }
    }


def _fake_usability_plot_summary(qc, usability_mdl=None, **kwargs):
    r2 = np.asarray(qc["NSI"]["Ridge"]["Lambda10"]["R2"], dtype=float)
    nsi = float(np.nanmedian(r2))
    return {
        "usability": {
            "summary_statistic": "median",
            "summary_nsi": nsi,
            "NSI_mean": nsi,
            "p_hat": nsi,
            "ci95": [max(0.0, nsi - 0.1), min(1.0, nsi + 0.1)],
            "decision": "Moderate (0.4-0.6)",
            "thresholds": {"P": [0.2, 0.4, 0.6], "NSI": [0.2, 0.3, 0.4]},
            "expert_judgement_j": {"min": 0.39, "mean": 0.43, "max": 0.488},
        }
    }


def _fake_batch_dist(nsi_values, usability_mdl=None, **kwargs):
    p_hat = np.asarray(nsi_values, dtype=float)
    return {
        "n": int(p_hat.size),
        "mean_p_hat": float(np.nanmean(p_hat)),
        "nsi": p_hat,
        "p_hat": p_hat,
        "summary": [{"category": "Moderate (0.4-0.6)", "count": int(p_hat.size), "percent": 100.0}],
    }


class TestCliConsistency(unittest.TestCase):
    def test_run_and_batch_use_same_usability_summary_statistic(self):
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td) / "out"
            outdir.mkdir()
            model_path = Path(td) / "nsi_usability_model.json.gz"
            model_path.write_bytes(b"placeholder")

            parser = cli.build_parser()
            run_args = parser.parse_args(
                [
                    "run",
                    "--cifti",
                    "/tmp/sub-01.dtseries.nii",
                    "--outdir",
                    str(outdir),
                    "--prefix",
                    "sub01",
                    "--no-save-figs",
                    "--usability-model",
                    str(model_path),
                ]
            )
            batch_args = parser.parse_args(
                [
                    "batch",
                    "--batch-input",
                    "cifti-list",
                    "--cifti-list",
                    "/tmp/sub-01.dtseries.nii",
                    "--outdir",
                    str(outdir),
                    "--prefix",
                    "sub01",
                    "--no-save-figs",
                    "--usability-model",
                    str(model_path),
                ]
            )

            with mock.patch("pfm_nsi.cli.prepare_cifti_for_mesh", return_value={"data": np.ones((3, 10))}), \
                mock.patch("pfm_nsi.cli.pfm_nsi", return_value=(_fake_qc(), {})), \
                mock.patch("pfm_nsi.cli._load_usability_model", return_value={"model": {}, "grid": {}, "thresholds": {}}), \
                mock.patch("pfm_nsi.cli.pfm_nsi_plots", side_effect=_fake_usability_plot_summary), \
                mock.patch("pfm_nsi.cli.plot_nsi_usability_distribution", side_effect=_fake_batch_dist):
                self.assertEqual(cli.run(run_args), 0)
                self.assertEqual(cli.batch(batch_args), 0)

            usability_json = json.loads((outdir / "sub01_usability.json").read_text())
            self.assertEqual(usability_json["summary_statistic"], "median")
            self.assertAlmostEqual(usability_json["summary_nsi"], 0.2, places=8)
            self.assertAlmostEqual(usability_json["p_hat"], 0.2, places=8)

            with (outdir / "sub01_batch_summary.csv").open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(float(rows[0]["nsi"]), 0.2, places=8)
            self.assertAlmostEqual(float(rows[0]["p_hat"]), 0.2, places=8)

            batch_json = json.loads((outdir / "sub01_batch_summary.json").read_text())
            self.assertEqual(batch_json["summary_statistic"], "median")

    def test_help_groups_present(self):
        parser = cli.build_parser()
        run_parser = parser._subparsers._group_actions[0].choices["run"]
        help_text = run_parser.format_help()
        self.assertIn("Input/Output", help_text)
        self.assertIn("Usability Mode", help_text)
        self.assertIn("Reliability Mode", help_text)
        self.assertIn("Plotting/Reporting", help_text)
        self.assertIn("Performance/Runtime", help_text)


class TestReliabilityExtrapolation(unittest.TestCase):
    def test_out_of_range_is_flagged_in_stdout_and_output(self):
        qc = {"NSI": {"MedianScore": 0.033}}
        reliability_model = {
            "Rmax_global": 0.8,
            "early": [
                {
                    "EARLY_MIN": 5,
                    "NSI_range": [0.104, 0.9],
                    "k_model": {
                        "beta": [0.01, 0.0],
                        "cov": [[0.0, 0.0], [0.0, 0.0]],
                        "rmse": 0.0,
                        "dfe": 10,
                        "form": "linear",
                    },
                    "Rmax_model": {
                        "beta": [0.8, 0.0],
                        "cov": [[0.0, 0.0], [0.0, 0.0]],
                        "rmse": 0.0,
                        "dfe": 10,
                        "form": "linear",
                    },
                    "query": [
                        {
                            "T_QUERY": 60,
                            "prob_models": [
                                {
                                    "R_thresh": 0.6,
                                    "mdl": {"beta": [-1.0, 2.0], "coef_names": ["(Intercept)", "NSI"]},
                                    "grid": {
                                        "NSI": [0.1, 0.3, 0.6],
                                        "P_med": [0.2, 0.5, 0.9],
                                        "P_lo": [0.1, 0.4, 0.8],
                                        "P_hi": [0.3, 0.6, 0.95],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        buf = io.StringIO()
        with redirect_stdout(buf):
            out = conditional_reliability_from_nsi(
                qc,
                reliability_model,
                nsi_t=5,
                query_t=60,
                thresholds=[0.6],
                verbose=True,
                do_plot=False,
            )
        text = buf.getvalue()

        self.assertIn("outside training range", text)
        self.assertIn("outside-training-range extrapolations", text)
        self.assertEqual(out["extrapolation"]["status"], "outside_training_range")
        self.assertFalse(out["extrapolation"]["in_training_range"])
        self.assertTrue(out["deterministic"]["is_extrapolated"])


if __name__ == "__main__":
    unittest.main()
