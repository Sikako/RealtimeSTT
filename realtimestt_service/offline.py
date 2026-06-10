import logging
import os


def configure_offline_environment(models_dir: str):
    os.environ["TORCH_HOME"] = models_dir
    os.environ["HF_HUB_OFFLINE"] = "1"


def patch_torch_hub_for_offline_silero(
    torch_module, models_dir: str, logger: logging.Logger
):
    if getattr(torch_module.hub.load, "_realtimestt_offline_patch", False):
        return

    original_load = torch_module.hub.load

    def offline_torch_hub_load(repo_or_dir, model, *args, **kwargs):
        if "silero-vad" in repo_or_dir:
            local_repo_path = os.path.join(
                models_dir,
                "hub",
                "snakers4_silero-vad_master",
            )
            if os.path.exists(local_repo_path):
                logger.info(
                    "Redirecting Silero VAD load to local path: %s", local_repo_path
                )
                kwargs["source"] = "local"
                return original_load(local_repo_path, model, *args, **kwargs)

            logger.warning(
                "Silero VAD local path not found: %s, falling back to default.",
                local_repo_path,
            )

        return original_load(repo_or_dir, model, *args, **kwargs)

    offline_torch_hub_load._realtimestt_offline_patch = True
    offline_torch_hub_load._realtimestt_original_load = original_load
    torch_module.hub.load = offline_torch_hub_load
