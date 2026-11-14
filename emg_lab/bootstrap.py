"""Composition root: the only wiring between the concrete backend and Qt frontend."""


def build_service(data_root):
    from emg_lab.backend.application import ApplicationService

    return ApplicationService(data_root)


def main():
    from emg_lab.frontend.window import main as launch

    return launch()
