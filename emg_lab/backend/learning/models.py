"""Replaceable classification networks with a shared [B, C, W] → [B, K] contract."""

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch import nn
ModelFactory = Callable[[tuple[int, int], int, dict], "nn.Module"]
DEFAULT_ARCHITECTURE = "LiteCNN1D_channels_v2"


def _baseline(input_shape: tuple[int, int], num_classes: int, config: dict):
    from .network import LiteCNN1D

    if config:
        raise ValueError("The baseline architecture has no model_config options.")
    return LiteCNN1D(*input_shape, num_classes)


_FACTORIES: dict[str, ModelFactory] = {DEFAULT_ARCHITECTURE: _baseline}


def register_model(name: str, factory: ModelFactory) -> None:
    """Register trusted Python code; model archives never contain executable factories."""
    if not name or name in _FACTORIES:
        raise ValueError(f"Architecture is empty or already registered: {name!r}")
    _FACTORIES[name] = factory


def build_model(
    architecture: str, model_config: dict, input_shape: tuple[int, int], num_classes: int
) -> "nn.Module":
    """Build a classifier. input_shape is (channels, window_samples); outputs are logits."""
    try:
        factory = _FACTORIES[architecture]
    except KeyError as exc:
        raise ValueError(
            f"Unknown architecture {architecture!r}; register it before training."
        ) from exc
    return factory(input_shape, num_classes, dict(model_config))
