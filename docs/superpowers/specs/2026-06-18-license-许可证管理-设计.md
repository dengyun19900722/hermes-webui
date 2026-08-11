# License 管理模块设计规格

## 1. 概述

为 Hermes Web UI 增加 License 管理功能，实现现场客户端的授权控制。

### 1.1 核心流程

1. 现场客户端首次使用时显示 License 申请页面，展示平台 ID 和 MAC 地址
2. 用户将平台 ID 和 MAC 地址复制发送给公司管理员
3. 公司管理员在管理端手动填入信息，生成 License 文件
4. 用户导入 License 文件，系统验证通过后解锁全部功能
5. 每次页面访问都验证 License 有效性，过期则完全锁定

### 1.2 关键设计决策

- **激活模式**：未激活状态直接展示申请页面，引导导入 License
- **校验方式**：每次访问页面验证 License 有效性
- **过期处理**：完全锁定，显示过期提示
- **数据传递**：纯手动传递（现场复制信息 → 管理员手动填入 → 生成文件）
- **加密方式**：AES-256-CBC 对称加密，共用密钥

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    现场客户端                            │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────┐  │
│  │License申请页│    │ License导入  │    │License校验│  │
│  │ 显示平台ID  │───▶│  导入.lic文件 │───▶│每次访问验证│  │
│  │ + MAC地址   │    │  AES解密校验  │    │           │  │
│  └─────────────┘    └──────────────┘    └───────────┘  │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐│
│  │ 系统管理 ── License 信息查看（状态/详情）          ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
                        │ .lic 文件
                        ▼
┌─────────────────────────────────────────────────────────┐
│                   公司管理端                             │
│  ┌──────────────────┐    ┌─────────────────────────┐   │
│  │ 接收申请(平台ID   │───▶│ 生成License:            │   │
│  │  + MAC)          │    │ AES加密串              │   │
│  │                  │    │  输出.lic文本文件        │   │
│  └──────────────────┘    └─────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. License 格式与加密

### 3.1 License 文件格式

公司生成并提供给现场的 license 文件（纯文本）：

```
a1b2c3d4e5f6...  （AES 加密后的 base64 字符串）
```

### 3.2 加密算法

使用 AES 对称加密（AES-256-CBC）：

```
明文 = platform_id + "|" + mac_address + "|" + expires_at
encrypted = AES_encrypt(明文, secret_key)
license_string = base64(encrypted)
```

**生成时（公司端）：**
1. 拼接明文信息
2. 用 secret_key 作为密钥进行 AES-256-CBC 加密
3. 输出 base64 编码字符串

**解密时（现场端）：**
1. 用 secret_key 作为密钥进行 AES-256-CBC 解密
2. 解析出 platform_id、mac_address、expires_at
3. 与本机信息对比验证

- `secret_key`：公司端和现场端共用密钥，存储在 `{workspace}/.license/secret_key`
- AES 加密保证了信息的机密性和完整性

### 3.3 License 导入验证流程

1. 用户上传 license 文件（纯 base64 字符串）
2. 用 secret_key 进行 AES-256-CBC 解密
3. 解析出 platform_id、mac_address、expires_at
4. 验证 license 文件中的 `platform_id` 与本机生成的 platform_id 一致（根据当前 MAC 生成）
5. 验证 license 文件中的 `mac_address` 与本机真实 MAC 地址一致
6. 验证当前时间 < `expires_at`
7. 全部通过则激活成功，更新 license.json：
   - `activated: true`
   - `mac_hash: SHA256(secret_key + MAC)`
   - `expires_at`
   - `imported_at`

**防拷贝设计：**
- Platform ID 根据 secret_key + 真实 MAC + 固定盐值通过 SHA256 生成，不是随机值
- 同一台机器的 platform_id 是固定的，无法拷贝到其他机器使用
- MAC 地址通过哈希存储防篡改

### 3.4 页面访问校验流程

每次页面访问时：
1. 获取本机真实 MAC 地址
2. 根据 secret_key + MAC + 盐值动态生成 platform_id
3. 计算本机 MAC 的哈希：`mac_hash = SHA256(secret_key + MAC)`
4. 检查 license.json 中 `activated` 是否为 true
5. 若为 true，对比 `mac_hash` 与 license.json 中存储的是否一致（防拷贝验证）
6. 若一致，检查当前时间是否 < `expires_at`
7. 若已过期或哈希不一致，清除 `activated` 状态，跳转到 License 申请页面
8. 若未激活，跳转到 License 申请页面

---

## 4. API 设计

### 4.1 现场客户端 API

#### GET `/api/license/status`
获取当前 License 状态。

**响应：**
```json
{
  "activated": true,
  "expires_at": "2027-06-30T23:59:59Z",
  "platform_id": "PLAT-123456",
  "days_remaining": 365
}
```

未激活时：
```json
{
  "activated": false,
  "expires_at": null,
  "platform_id": "PLAT-123456",
  "days_remaining": null
}
```

注：platform_id 和 mac_hash 根据当前 MAC 动态生成，不是存储在文件中的固定值。

#### POST `/api/license/apply`
获取本机平台信息（用于用户复制给管理员）。

**响应：**
```json
{
  "platform_id": "PLAT-123456",
  "mac_address": "AA:BB:CC:DD:EE:FF"
}
```

注：platform_id 根据当前 MAC 动态生成，用户将这两个信息发送给管理员以生成 license。

#### POST `/api/license/import`
导入 License 文件。

**请求：**
- Content-Type: `multipart/form-data`
- 文件：license 文件（纯文本，AES 加密后的 base64 字符串）

**响应（成功）：**
```json
{
  "ok": true,
  "expires_at": "2027-06-30T23:59:59Z"
}
```

**响应（失败）：**
```json
{
  "ok": false,
  "error": "解密失败" | "平台ID不匹配" | "MAC地址不匹配" | "License已过期"
}
```

#### GET `/api/license/info`
获取当前 License 详细信息（系统管理页面用）。

**响应：**
```json
{
  "activated": true,
  "platform_id": "PLAT-123456",
  "expires_at": "2027-06-30T23:59:59Z",
  "imported_at": "2026-06-18T10:00:00Z",
  "days_remaining": 365,
  "status": "valid" | "expired" | "not_activated"
}
```

注：platform_id 和 mac_hash 根据当前 MAC 动态生成，不是存储在文件中的固定值。

### 4.2 公司管理端 API

#### POST `/api/admin/license/generate`
生成 License 文件。

**请求：**
```json
{
  "platform_id": "PLAT-123456",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "expires_at": "2027-06-30T23:59:59Z"
}
```

**响应：**
```json
{
  "ok": true,
  "license_string": "a1b2c3d4e5f6..."
}
```

管理员下载生成的 license 字符串，提供给用户导入。

#### GET `/api/admin/license/list`
获取已生成的 License 列表。

**响应：**
```json
{
  "licenses": [
    {
      "platform_id": "PLAT-123456",
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "expires_at": "2027-06-30T23:59:59Z",
      "generated_at": "2026-06-18T10:00:00Z"
    }
  ]
}
```

### 4.3 生成 License 调用示例

管理员在服务端执行 curl 命令生成 License：

```bash
curl -s -X POST http://127.0.0.1:7000/api/admin/license/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "platform_id": "PLAT-57C8FF",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "expires_at": "2026-12-31T23:59:59Z"
  }'
```

**响应：**
```json
{
  "ok": true,
  "license_string": "a1b2c3d4e5f6..."
}
```

将 `license_string` 的值保存为 `.lic` 文件，提供给现场用户导入。

**一键生成脚本（自动获取本机信息）：**
```bash
# 先获取本机平台 ID 和 MAC
INFO=$(curl -s http://127.0.0.1:7000/api/license/apply -X POST -H 'Content-Type: application/json' -d '{}')
PID=$(echo $INFO | python3 -c "import sys,json; print(json.load(sys.stdin)['platform_id'])")
MAC=$(echo $INFO | python3 -c "import sys,json; print(json.load(sys.stdin)['mac_address'])")

# 用获取到的信息生成 License
curl -s -X POST http://127.0.0.1:7000/api/admin/license/generate \
  -H 'Content-Type: application/json' \
  -d "{\"platform_id\": \"$PID\", \"mac_address\": \"$MAC\", \"expires_at\": \"2026-12-31T23:59:59Z\"}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('license_string','ERROR: '+str(d)))" > license.lic
```

参数说明：
- `platform_id`：从 License 申请页获取，格式 `PLAT-XXXXXX`
- `mac_address`：从 License 申请页获取，格式 `AA:BB:CC:DD:EE:FF`
- `expires_at`：过期时间，ISO 8601 格式（`2026-12-31T23:59:59Z`）

---

## 5. 数据存储

### 5.1 License 配置文件

路径：`{workspace}/.license/`

```
{workspace}/
  └── .license/
        ├── secret_key    # AES-256 加密密钥
        └── license.json  # License 信息
```

**secret_key 文件：**
- 纯文本文件，包含 AES 加密密钥
- 由公司在生成 license 前放置到现场 workspace

**license.json 文件：**
```json
{
  "activated": false,
  "mac_hash": "a1b2c3d4e5f6...",
  "expires_at": null,
  "imported_at": null
}
```

注：
- `platform_id` 不存储，每次根据 secret_key + MAC + 盐值动态生成
- `mac_hash` 存储，用于防拷贝验证（SHA256(secret_key + MAC)）
- license.json 本地存储激活状态，license 文件（加密串）由用户提供

**初始化流程：**
1. 应用启动时检查 `{workspace}/.license/secret_key` 文件
2. 若不存在，提示错误并阻止进入系统
3. 若存在，检查 license.json 是否存在
4. 若不存在，创建 license.json
5. 自动获取本机 MAC 地址
6. 根据 `secret_key + MAC地址 + 固定盐值` 生成 platform_id（格式：`PLAT-` + SHA256前6位）
7. 计算 `mac_hash = SHA256(secret_key + MAC地址)` 并存储
8. activated 初始为 false

- `.license` 目录在 workspace 下创建，与项目文件隔离
- License 文件跟随 workspace，便于管理
- secret_key 由公司提供，现场不能修改

---

## 6. 前端页面

### 6.1 License 申请页面（未激活时显示）

全屏覆盖，显示：
- 本机平台 ID（可复制）
- 本机 MAC 地址（可复制）
- "复制信息" 按钮
- "导入 License 文件" 按钮（上传 license 文件，包含加密字符串）
- 提示：将平台 ID 和 MAC 地址发送给管理员，获取 license 文件

### 6.2 系统管理 - License 信息子页面

入口：系统管理菜单 → License 管理

显示内容：
- 当前 License 状态（有效/过期/未激活）
- 平台 ID
- MAC 地址
- 过期时间
- 剩余天数
- 导入时间

---

## 7. 安全考虑

1. **密钥管理**：`secret_key` 文件由公司提供，现场不能修改或删除
2. **AES 加密**：使用 AES-256-CBC 加密，保证 license 信息机密性和完整性
3. **机器绑定**：Platform ID 根据 secret_key + MAC + 固定盐值生成，无法拷贝到其他机器
4. **防拷贝验证**：MAC 地址哈希存储（SHA256(secret_key + MAC)），每次访问验证，防止 license.json 被拷贝盗用
5. **过期检查**：每次访问都检查过期时间

---

## 8. 实现文件清单

### 后端
- `api/license.py` - License 模块（新建）
- `api/routes.py` - 添加 License 相关路由

### 前端
- `static/panels.js` - 添加 License 管理面板
- `static/index.html` - 添加 License 申请页面结构
- `static/style.css` - 补充 License 页面样式

### 配置
- `docs/` - 补充 License 管理使用说明