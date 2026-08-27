from llama_cpp import Llama

# 只 load 一次
llm = Llama(
    model_path="你的模型.gguf",
    n_ctx=8192,          # 依你 VRAM 調整
    n_gpu_layers=-1,     # 全部丟 GPU，或指定層數
    verbose=False,
)

# 自己管理 history
messages = [
    {"role": "system", "content": "你是有用的助手"},
]

def chat(user_input: str):
    messages.append({"role": "user", "content": user_input})
    response = llm.create_chat_completion(
        messages=messages,
        temperature=0.7,
        max_tokens=1024,
    )
    reply = response["choices"][0]["message"]["content"]
    messages.append({"role": "assistant", "content": reply})
    return reply

def clear_memory():
    global messages
    # 只保留 system prompt，或直接清空
    messages = [m for m in messages if m["role"] == "system"]
    # 或 messages = []
    print("content memory 已清空，模型權重仍在記憶體")

# 使用
print(chat("你好"))
print(chat("我叫小明"))
clear_memory()          # 瞬間清，不用 reload
print(chat("我叫什麼名字？"))  # 模型已經不記得了