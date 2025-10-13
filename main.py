from RealtimeSTT import AudioToTextRecorder

if __name__ == '__main__':
    print("開始即時語音轉文字...")

    def process_text(text):
        """
        在收到最終轉錄結果時被呼叫的回呼函式。
        """
        print(f"最終結果: {text}")

    # 建立錄音機實例，並確保模型在本地運行
    # model="tiny.en" or "small.en" or "base.en" or "medium.en"
    # language="en" or "zh"
    recorder = AudioToTextRecorder(
        model="./models/faster-whisper-small",
        language="zh",
        webrtc_sensitivity=3
    )

    print("請開始說話...")

    try:
        while True:
            # 從麥克風讀取音訊並進行轉錄
            recorder.text(process_text)
    except KeyboardInterrupt:
        print("\n程式已停止。")
        recorder.stop()
