function p = local_predict_binom_logit(mdl, NSI_te)
x = NSI_te - mdl.muNSI;
switch mdl.form
    case 'linear'
        eta = mdl.beta(1) + mdl.beta(2) .* x(:);
    case 'quadratic'
        eta = mdl.beta(1) + mdl.beta(2) .* x(:) + mdl.beta(3) .* (x(:).^2);
    otherwise
        error('Bad model form');
end
p = 1 ./ (1 + exp(-eta));
p = reshape(p, size(NSI_te));
end