# 配置片段

## 定义 provider（写在用户级 `~/.codex/config.toml`）

```toml
[model_providers.example]
name = "Example Provider"
base_url = "https://example.com/v1"
wire_api = "responses"
requires_openai_auth = false
auth.command = "/usr/bin/python3"
auth.args = ["/绝对路径/auth.py"]
auth.timeout_ms = 5000
auth.refresh_interval_ms = 300000
```

要点：

- `wire_api = "responses"` 是前提，提供方必须支持 Responses API。
- `auth.command` 的标准输出就是 token，Codex 会自动 trim；空输出视为失败。
- 不要同时写 `env_key`、`experimental_bearer_token`、`requires_openai_auth = true`，它们与 `auth.command` 冲突。
- 不用自定义 provider 也可以只改 `openai_base_url`（把内置 openai provider 指到代理），但那样原生模型也会被改道。

## 切到第三方模型（桌面端与 CLI 的默认）

```toml
model = "example-model"
model_provider = "example"
model_catalog_json = "/绝对路径/models.json"
```

切回原生：删掉这三行，或按 `switch-mode.sh` 的方式处理。

## 仅单次运行（CLI）

```sh
codex -c model_provider="example" -c model="example-model" \
  -c 'model_providers.example.base_url="https://example.com/v1"' \
  -c 'model_providers.example.wire_api="responses"' \
  -c 'model_providers.example.auth.command="/usr/bin/python3"' \
  -c 'model_providers.example.auth.args=["/绝对路径/auth.py"]'
```

`-c` 的值按 TOML 解析，字符串要带引号。这种写法不会动用户的默认配置，适合先做验证。

## 取钥脚本的最小形态

```python
#!/usr/bin/env python3
import os, sys
from pathlib import Path

key = os.environ.get("EXAMPLE_API_KEY", "").strip()
if not key:
    path = Path.home() / ".config" / "example" / "key"
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        sys.exit(f"Missing API key: set EXAMPLE_API_KEY or write {path}")
sys.stdout.write(key)
```

文件权限应为 600；不要把 key 打印到日志或终端回显里。

## 项目级配置的限制

仓库里的 `.codex/config.toml` 不能设置 `model_provider`、`model_providers`、`openai_base_url` 这类会重定向凭据或请求地址的键，Codex 会忽略并给出 warning。这些键只能写在用户级配置里。
