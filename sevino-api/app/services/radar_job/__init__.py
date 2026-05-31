class RadarJobError(Exception):
    """A stage of the radar batch pipeline could not proceed.

    Carries a short machine code (e.g. ``"llm_validation_failed"``,
    ``"pool too small"``) so the T5 orchestrator can log it and let ARQ
    retry the whole task. Stages raise this instead of bubbling raw
    provider/DB errors so the orchestrator has one failure type to catch.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
