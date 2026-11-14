"""Trusted model factory extension contract, without altering recording labels."""

import pytest
import torch
from torch import nn

from emg_lab.backend.learning.models import DEFAULT_ARCHITECTURE, build_model, register_model


def test_default_model_preserves_logits_shape():
    model = build_model(DEFAULT_ARCHITECTURE, {}, (4, 500), 7).eval()
    with torch.no_grad():
        assert model(torch.zeros(2, 4, 500)).shape == (2, 7)


def test_custom_factory_receives_shape_classes_and_copied_config():
    seen = []

    def factory(shape, classes, config):
        seen.append((shape, classes, config.pop("width")))
        return nn.Sequential(nn.Flatten(), nn.Linear(shape[0] * shape[1], classes))

    register_model("test-linear-classifier", factory)
    config = {"width": 8}
    model = build_model("test-linear-classifier", config, (4, 100), 3)
    assert model(torch.zeros(2, 4, 100)).shape == (2, 3)
    assert config == {"width": 8} and seen == [((4, 100), 3, 8)]
    with pytest.raises(ValueError, match="already registered"):
        register_model("test-linear-classifier", factory)


def test_invalid_factory_selection_is_explicit():
    with pytest.raises(ValueError, match="Unknown architecture"):
        build_model("missing", {}, (4, 500), 4)
    with pytest.raises(ValueError, match="no model_config"):
        build_model(DEFAULT_ARCHITECTURE, {"invented": True}, (4, 500), 4)
