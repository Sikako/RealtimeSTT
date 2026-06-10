"""Manual RealtimeSTT microphone demo.

This is intentionally not a pytest test. It opens the microphone, can type
transcribed text into the active window, and may download models only when
started with --allow-download.
"""

EXTENDED_LOGGING = False

DEFAULT_MODEL_DIRNAME = "faster-whisper-small"

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Start the manual realtime Speech-to-Text (STT) microphone demo."
    )

    parser.add_argument(
        "-m",
        "--model",
        type=str,
        help=(
            "Local STT model path, model size, or Hugging Face CTranslate2 model. "
            "Without --allow-download this must be an existing local path. "
            "Default is models/faster-whisper-small."
        ),
    )

    parser.add_argument(
        "-r",
        "--rt-model",
        "--realtime_model_type",
        type=str,
        help=(
            "Realtime transcription model. Without --allow-download this must be "
            "an existing local path. Default is the same value as --model."
        ),
    )

    parser.add_argument(
        "-l",
        "--lang",
        "--language",
        type=str,
        default="en",
        help="Language code for transcription. Use an empty value for auto-detection. Default is en.",
    )

    parser.add_argument(
        "-d",
        "--root",
        type=str,
        help="Local models root. Default is the repository models directory.",
    )

    parser.add_argument(
        "-dev",
        "--device",
        type=str,
        default="cpu",
        help="Device to use for computation. Options: cpu, cuda. Default is cpu.",
    )

    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow RealtimeSTT/faster-whisper/torch.hub to download missing models.",
    )

    parser.add_argument(
        "--write-to-keyboard",
        action="store_true",
        help="Type final transcriptions into the currently focused window.",
    )

    parser.add_argument(
        "--keyboard-interval",
        type=float,
        default=0.002,
        help="Delay between typed characters when --write-to-keyboard is enabled.",
    )

    args = parser.parse_args()

    if EXTENDED_LOGGING:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    from rich.console import Console
    from rich.live import Live
    from rich.text import Text
    from rich.panel import Panel

    console = Console()
    console.print("System initializing, please wait")

    import os

    # Fix for "mkl_malloc: failed to allocate memory" error on CPU
    # This limits the number of threads used by the MKL library, reducing memory pressure.
    os.environ["MKL_NUM_THREADS"] = "1"

    import sys

    def looks_like_local_path(value):
        return (
            os.path.isabs(value)
            or os.path.sep in value
            or (os.path.altsep is not None and os.path.altsep in value)
        )

    def require_local_model(label, value):
        if args.allow_download:
            return
        if not looks_like_local_path(value) or not os.path.isdir(value):
            parser.error(
                f"{label} must be an existing local model path when --allow-download "
                f"is not set: {value}"
            )

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_root = os.path.abspath(args.root or os.path.join(base_dir, "models"))
    model_path = args.model or os.path.join(models_root, DEFAULT_MODEL_DIRNAME)
    realtime_model_path = args.rt_model or model_path

    os.environ["TORCH_HOME"] = models_root
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if not args.allow_download:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    require_local_model("--model", model_path)
    require_local_model("--rt-model", realtime_model_path)

    print(f"Environment variable TORCH_HOME set to: {models_root}")
    if args.allow_download:
        print("Model downloads are allowed for this run.")
    else:
        print("Offline mode is enabled. Use --allow-download to permit model downloads.")

    from RealtimeSTT import AudioToTextRecorder
    import colorama
    import pyautogui

    if os.name == "nt" and (3, 8) <= sys.version_info < (3, 99):
        from torchaudio._extension.utils import _init_dll_path

        _init_dll_path()

    colorama.init()

    # Initialize Rich Console and Live
    live = Live(console=console, refresh_per_second=10, screen=False)
    live.start()

    full_sentences = []
    rich_text_stored = ""
    recorder = None
    displayed_text = ""  # Used for tracking text that was already displayed

    end_of_sentence_detection_pause = 0.45
    unknown_sentence_detection_pause = 0.7
    mid_sentence_detection_pause = 2.0

    def clear_console():
        os.system("clear" if os.name == "posix" else "cls")

    prev_text = ""

    def preprocess_text(text):
        # Remove leading whitespaces
        text = text.lstrip()

        #  Remove starting ellipses if present
        if text.startswith("..."):
            text = text[3:]

        # Remove any leading whitespaces again after ellipses removal
        text = text.lstrip()

        # Uppercase the first letter
        if text:
            text = text[0].upper() + text[1:]

        return text

    def text_detected(text):
        global prev_text, displayed_text, rich_text_stored

        text = preprocess_text(text)

        sentence_end_marks = [".", "!", "?", "。"]
        if text.endswith("..."):
            recorder.post_speech_silence_duration = mid_sentence_detection_pause
        elif (
            text
            and text[-1] in sentence_end_marks
            and prev_text
            and prev_text[-1] in sentence_end_marks
        ):
            recorder.post_speech_silence_duration = end_of_sentence_detection_pause
        else:
            recorder.post_speech_silence_duration = unknown_sentence_detection_pause

        prev_text = text

        # Build Rich Text with alternating colors
        rich_text = Text()
        for i, sentence in enumerate(full_sentences):
            if i % 2 == 0:
                # rich_text += Text(sentence, style="bold yellow") + Text(" ")
                rich_text += Text(sentence, style="yellow") + Text(" ")
            else:
                rich_text += Text(sentence, style="cyan") + Text(" ")

        # If the current text is not a sentence-ending, display it in real-time
        if text:
            rich_text += Text(text, style="bold yellow")

        new_displayed_text = rich_text.plain

        if new_displayed_text != displayed_text:
            displayed_text = new_displayed_text
            panel = Panel(
                rich_text,
                title="[bold green]Live Transcription[/bold green]",
                border_style="bold green",
            )
            live.update(panel)
            rich_text_stored = rich_text

    def process_text(text):
        global recorder, full_sentences, prev_text
        recorder.post_speech_silence_duration = unknown_sentence_detection_pause

        text = preprocess_text(text)
        text = text.rstrip()
        if text.endswith("..."):
            text = text[:-2]

        if not text:
            return

        full_sentences.append(text)
        prev_text = ""
        text_detected("")

        if args.write_to_keyboard:
            pyautogui.write(
                f"{text} ", interval=args.keyboard_interval
            )

    # Recorder configuration
    recorder_config = {
        "spinner": False,
        "model": model_path,
        "download_root": models_root,
        # 'input_device_index': 1,
        "realtime_model_type": realtime_model_path,
        "language": args.language or None,
        "silero_sensitivity": 0.05,
        "webrtc_sensitivity": 3,
        "post_speech_silence_duration": unknown_sentence_detection_pause,
        "min_length_of_recording": 1.1,
        "min_gap_between_recordings": 0,
        "enable_realtime_transcription": True,
        "realtime_processing_pause": 0.02,
        "on_realtime_transcription_update": text_detected,
        #'on_realtime_transcription_stabilized': text_detected,
        "silero_deactivity_detection": True,
        "early_transcription_on_silence": 0,
        "beam_size": 5,
        "beam_size_realtime": 3,
        # 'batch_size': 0,
        # 'realtime_batch_size': 0,
        "no_log_file": True,
        "initial_prompt_realtime": (
            "End incomplete sentences with ellipses.\n"
            "Examples:\n"
            "Complete: The sky is blue.\n"
            "Incomplete: When the sky...\n"
            "Complete: She walked home.\n"
            "Incomplete: Because he...\n"
        ),
        "silero_use_onnx": True,
        "faster_whisper_vad_filter": False,
        "device": args.device,
    }

    # args are parsed before this block

    # Automatically locate or facilitate download of the VAD model
    expected_vad_path = os.path.join(
        models_root,
        "hub",
        "snakers4_silero-vad_master",
        "silero_vad.onnx",
    )
    if os.path.exists(expected_vad_path):
        recorder_config["silero_model_path"] = expected_vad_path
        print(f"Found local Silero VAD model at: {expected_vad_path}")
    elif not args.allow_download:
        parser.error(
            "Local Silero VAD model not found and --allow-download is not set: "
            f"{expected_vad_path}"
            )
    else:
        print(
            "Local Silero VAD model not found. RealtimeSTT may download it to: "
            f"{expected_vad_path}"
        )

    if EXTENDED_LOGGING:
        recorder_config["level"] = logging.DEBUG

    recorder = AudioToTextRecorder(**recorder_config)

    initial_text = Panel(
        Text("Say something...", style="cyan bold"),
        title="[bold yellow]Waiting for Input[/bold yellow]",
        border_style="bold yellow",
    )
    live.update(initial_text)

    try:
        while True:
            recorder.text(process_text)
    except KeyboardInterrupt:
        live.stop()
        console.print("[bold red]Transcription stopped by user. Exiting...[/bold red]")
        exit(0)
