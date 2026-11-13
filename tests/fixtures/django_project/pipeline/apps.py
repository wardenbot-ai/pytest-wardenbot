from django.apps import AppConfig


class PipelineConfig(AppConfig):
    name = "pipeline"

    def ready(self) -> None:
        # Some applications build their client while Django sets up.
        from pipeline import llm

        llm.build_ready_client()
