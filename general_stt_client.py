import asyncio
import websockets
import json
import time
import argparse
import sys
import wave

# 設定
CHUNK_SIZE = 1024
RATE = 16000

def get_audio_generator(args):
    """
    根據模式回傳一個 async generator，產出 bytes (PCM 16k)
    """
    if args.mode == 'mic':
        import pyaudio
        p = pyaudio.PyAudio()
        input_device_index = None # 預設

        # 簡單列出裝置供參考
        info = p.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        print("--- Available Audio Devices ---")
        for i in range(0, numdevices):
            if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                print(f"Input Device id {i} - {p.get_device_info_by_host_api_device_index(0, i).get('name')}")
        print("-------------------------------")

        stream = p.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=RATE,
                        input=True,
                        input_device_index=input_device_index,
                        frames_per_buffer=CHUNK_SIZE)
        
        print(f"[*] Recording from microphone... (Ctrl+C to stop)")
        
        async def mic_gen():
            loop = asyncio.get_event_loop()
            try:
                while True:
                    # 使用 run_in_executor 避免阻塞 async loop
                    data = await loop.run_in_executor(None, stream.read, CHUNK_SIZE, False)
                    yield data
            except asyncio.CancelledError:
                pass
            finally:
                print("Stopping microphone stream...")
                stream.stop_stream()
                stream.close()
                p.terminate()

        return mic_gen()

    elif args.mode == 'file':
        if not args.path:
            raise ValueError("Mode 'file' requires --path arg")
        
        print(f"[*] Reading from file: {args.path}")
        
        async def file_gen():
            wf = wave.open(args.path, 'rb')
            if wf.getnchannels() != 1 or wf.getframerate() != 16000 or wf.getsampwidth() != 2:
                print(f"[!] Warning: File format is not 16k mono 16bit. Server might need resampling.")
                # 注意: 這裡為了簡單測試，假設使用者提供正確格式，或者 Server 端有實作重採樣
                # 若要 client 端轉檔可以使用 scipy 或 librosa，但此 script 保持輕量

            # 計算發送間隔以模擬即時
            interval = CHUNK_SIZE / RATE 
            
            data = wf.readframes(CHUNK_SIZE)
            while len(data) > 0:
                start_time = time.time()
                yield data
                
                # 模擬真實時間流逝
                elapsed = time.time() - start_time
                wait_time = interval - elapsed
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                data = wf.readframes(CHUNK_SIZE)
            
            wf.close()
            print("[*] File playback finished.")

        return file_gen()

async def receive_messages(websocket, user_id):
    """持續接收 Server 廣播回來的訊息"""
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                # 簡單過濾掉自己的訊息 (看需求) 或顯示出來
                speaker = data.get('channel_id', 'Unknown')
                text = data.get('text', '')
                if text:
                    print(f"\n[Session Broadcast] {speaker}: {text}")
            except:
                print(f"\n[Raw Message]: {message}")
    except websockets.exceptions.ConnectionClosed:
        print("\n[Disconnected] Connection closed by server.")

async def send_audio(websocket, generator):
    """持續發送音訊"""
    async for chunk in generator:
        try:
            await websocket.send(chunk)
        except websockets.exceptions.ConnectionClosed:
            break

async def start_client(args):
    uri = f"ws://localhost:8000/v1/audio/stream?session_id={args.session}&channel_id={args.user}"
    print(f"[*] Connecting to {uri} ...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("[*] Connected.")

            # 1. Send Config
            config = {
                "sample_rate": RATE,
                "encoding": "pcm_16",
                "language": "zh"
            }
            await websocket.send(json.dumps(config))
            print("[*] Config sent.")

            # 2. Start Tasks
            audio_gen = get_audio_generator(args)
            
            # 使用 gather 並行 "發送音訊" 與 "接收轉錄"
            sender_task = asyncio.create_task(send_audio(websocket, audio_gen))
            receiver_task = asyncio.create_task(receive_messages(websocket, args.user))
            
            # 等待 sender 完成 (例如檔案播放完畢)
            # 注意: 若是 mic 模式，sender_task 基本上不會結束 (除非例外)
            try:
                await sender_task
                print("[*] Audio sending finished. Keeping connection open for results... (Ctrl+C to exit)")
            except Exception as e:
                print(f"[!] Sender task error: {e}")

            # 保持接收，直到被中斷
            await receiver_task
                
    except websockets.exceptions.ConnectionClosed:
         print("[!] Disconnected (ConnectionClosed).")
    except Exception as e:
        print(f"[!] Connection error: {e}")
    finally:
        print("[*] Client closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="STT WebSocket Client")
    parser.add_argument("--mode", choices=['mic', 'file'], default='mic', help="Audio source: 'mic' or 'file'")
    parser.add_argument("--path", type=str, help="Path to .wav file (if mode is file)")
    parser.add_argument("--session", type=str, default="test_room", help="Session ID (Room)")
    parser.add_argument("--user", type=str, default="User_A", help="User ID (Channel)")
    
    args = parser.parse_args()
    
    try:
        asyncio.run(start_client(args))
    except KeyboardInterrupt:
        print("\n[*] Exiting...")
