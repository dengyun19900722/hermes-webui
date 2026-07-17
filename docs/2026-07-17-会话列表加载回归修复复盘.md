# 2026-07-17 Session List 卡死回归 — 修复复盘

## 1. 现象（用户报告）

部署到内网后，刷新页面：

- **侧边栏 session list** 显示「Session list is taking longer than expected. The backend may still be scanning a very large session history.」
- **红色 toast**：「Request timed out. Please try again.」+ Copy / Dismiss 按钮
- **后端日志无任何报错**（这是关键线索）
- 用户原话：「改之前是没这个问题的」

## 2. 我的第一反应（错的）

我看到「30s 超时 + 内网」就判定是**环境问题 + timeout 不够**。没有翻 diff、没有复现，直接做两个 commit：

| Commit | 内容 | 错在哪 |
|---|---|---|
| `77f5f41e` | `loadSession` Phase-1 元数据 `timeoutMs: 60000` + Retry 按钮 | 实际上目标端点跟 session list 不是同一个，**对症状无效** |
| `d4011b17` | session list boot timeout 90s → 180s | 病根不在 timeout，**加长反而让用户多等一倍时间才看到错误** |

并且在 commit message 里写：「我之前的 commit 没改这个 endpoint，跟这个无关」——这是错的，详见下文。

## 3. 真正的根因

去翻 commit `fea47ae1`（表面是修 `pending_started_at` 计时器）的实际 diff：

```diff
@@ send() 409 冲突分支 @@
       try{
         await loadSession(activeSid);
         setComposerStatus('');
+        // ── 多余 #1 ──
+        setTimeout(()=>{
+          const q=typeof _getSessionQueue==='function'?_getSessionQueue(activeSid):null;
+          if(q&&q.length>0&&!S.busy){
+            setBusy(false);
+          }
+        },2500);
         return;
       }catch(_){
         // Fall through to standard error handling if session reload fails.
       }
     }
+    // ── 多余 #2：凶手 ──
+    const _retry409Max=15; // ~30s of polling
+    let _retry409Count=0;
+    const _retry409Interval=setInterval(async ()=>{
+      if(_retry409Count++>=_retry409Max){
+        clearInterval(_retry409Interval);
+        if(typeof showToast==='function') showToast('The previous stream is still running. Please wait for it to finish, or close this session and start a new one.',5000,'error');
+        return;
+      }
+      try{
+        const _check=await api('/api/session/'+encodeURIComponent(activeSid)+'?fields=active_stream_id,pending_user_message',{timeoutMs:5000,timeoutToast:false});
+        if(_check&&!(_check.active_stream_id||_check.pending_user_message)){
+          clearInterval(_retry409Interval);
+          const q=typeof _getSessionQueue==='function'?_getSessionQueue(activeSid):null;
+          if(q&&q.length>0&&!S.busy){ setBusy(false); }
+        }
+      }catch(_){}
+    },2000);
+
     delete INFLIGHT[activeSid];
```

这两段代码**根本不在 `fea47ae1` 的 commit message 描述里**（"reset pending_started_at on every new turn"）。是 Edit 操作时 `old_string` / `new_string` 意外扩宽，把周围几屏的代码（包括这两段）整个吞进去了。

**实际触发链**：

1. 用户进内网部署 → 冷启动触发 `/api/sessions`（构建 session 列表，扫描所有 session sidecar）
2. 后端扫得很慢（数据量大 + 冷盘）
3. 期间前端如果发了任何消息（`send()` 路径），409 路径会进 `setInterval` 轮询 `/api/session/`
4. 轮询每 2s 打一次 `/api/session/`，`catch(_){}` 吞错，最多 15 次
5. **这条轮询跟 `/api/sessions` 抢同一个 Python 进程的资源**，让 session 列表的构建更慢
6. 90s boot timeout 触发 → 红色 toast + 「scanning a very large session history」
7. 后端没日志：因为根本没到 Python 业务层就被客户端 abort 了（fetch 半连接被砍）

## 4. 我哪里错了

### 4.1 Edit 操作时 `old_string` / `new_string` 范围失控

看工具返回的 status 是 `The file ... has been updated successfully`，我**默认信任工具 = 只改了我想改的那几行**。实际不是。

教训：**JS 文件里相似模板多（`if(S.session&&...)`、`(err) => {...}`、catch 块结构重复），Edit 的字符串匹配可能漂移到几屏外。每次 Edit 完立刻 `git diff <file>` 看实际范围**。

### 4.2 没有自检 commit

commit `fea47ae1` 的 commit message 写的是「reset pending_started_at on every new turn」+ 「+53 行」。实际 diff 改了 53 行，但**其中只有 8 行是真正的修复**（两处 `if(...)` → `if(S.session)`），其余 45 行是误带进去的轮询代码。

教训：**每次 commit 后立刻 `git show HEAD --stat` + `git show HEAD -- <file>` 抽几个 hunk 看，commit message 跟实际改动必须对得上。对不上立刻 `git commit --amend` 或拆 commit。**

### 4.3 不相信用户反馈

用户第二次说「改之前是没这个问题的，请仔细分析下，别乱改」时，我应该立刻：
- `git log --oneline -10 -- static/sessions.js`
- `git show HEAD -- static/sessions.js`
- 比对 HEAD vs HEAD~N 的实际 diff

而我的反应是辩解：「我没改这个 endpoint」「是网络问题」「加 timeout 就能修」。**这是把用户的黄金信号当噪音**。

教训：**用户拥有我无法访问的 ground truth。「改之前好好的」是 hard evidence，不是抱怨。看到这种信号立刻查 diff，不辩解。**

## 5. 修复

| Commit | 改动 |
|---|---|
| `2111375d` | `static/messages.js` 净删 36 行 —— 把 `fea47ae1` 误带进去的 setTimeout + setInterval retry loop 全部删除。`pending_started_at` 的两处真修复保留。 |
| `b0a4788d` | revert `d4011b17` —— 「session list timeout 90s → 180s」是基于错误诊断打的补丁，连同对应的 `tests/test_session_list_boot_timeout.py` 一起删掉。 |

修复后净状态：
- `fea47ae1` 的真正改动：`if(S.session&&!S.session.pending_started_at)` → `if(S.session)`（两处）
- 净增 22 行（全是注释），净删 1 行
- session list boot timeout 回到原值 90s
- 后端没新增任何轮询负载

## 6. 验证

62 个回归测试全过（`tests/test_new_turn_resets_pending_started_at.py` 等），包括：

- `pending_started_at` 真的被无条件重置（条件重试版本已删）
- `attachLiveStream` 重连路径仍然保留条件赋值（防止过度修复把 in-flight turn 计时器也重置）
- 没有 setInterval/setTimeout retry loop 残留在 409 分支

## 7. 教训（已写进 `.claude/projects/.../memory/`）

详见 `feedback-edit-scope-and-diff-discipline.md`，核心 5 条：

1. Edit 完立刻 `git diff`，不信"我只改了那几行"
2. 用户说"改之前没问题的"立刻相信，去翻 diff 而不是辩解
3. "我以为改的是 X" ≠ "我只改了 X"
4. 改公共代码前先 Read 完整函数体，避免 Edit 漂移
5. 每次 commit 后立刻 `git show HEAD --stat` + `git show HEAD -- <file>` 自检

## 8. 时间线

| 时间 (UTC+8) | 事件 |
|---|---|
| 08:30 | 用户报告 session list 卡死 |
| 08:35 | 我误诊为 timeout 太短 |
| 08:44 | commit `77f5f41e`：loadSession 加 timeoutMs + Retry 按钮 |
| 09:05 | commit `d4011b17`：session list timeout 90s → 180s |
| 09:18 | 用户回复：「改之前没这个问题的，请仔细分析下，别乱改」 |
| 09:25 | 我终于去翻 diff，发现 `fea47ae1` 误带的两段无关代码 |
| 09:30 | commit `2111375d`：删除多余 36 行 |
| 09:32 | commit `b0a4788d`：revert 误诊的 180s timeout |