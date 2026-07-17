# Beta Install Guide (Private GitHub)

This guide shows how to install `pfm-nsi` from a private GitHub repo for beta users.

## Option A: SSH (recommended)

1. Ensure you have an SSH key added to GitHub.
2. Install directly:

```bash
python -m pip install git+ssh://git@github.com/<ORG_OR_USER>/pfm-nsi.git
```

## Option B: HTTPS with Personal Access Token (PAT)

1. Create a GitHub PAT with `repo` scope.
2. Install using the token:

```bash
python -m pip install git+https://<TOKEN>@github.com/<ORG_OR_USER>/pfm-nsi.git
```

## Option C: Clone then install (editable)

```bash
git clone git@github.com:<ORG_OR_USER>/pfm-nsi.git
cd pfm-nsi
python -m pip install -e .
```

## Verify install

```bash
pfm-nsi -h
pfm-nsi run -h
```

## Troubleshooting

- If `pfm-nsi` is not found, ensure the install went to the active Python environment.
- If you get permission errors, confirm your GitHub access to the private repo.
