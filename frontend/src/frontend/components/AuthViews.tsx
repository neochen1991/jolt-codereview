import React, { useState } from "react";
import { Check, Circle, Zap } from "lucide-react";
import { User, PublishResultNotice } from "../shared";

export function AuthPage({
  currentUser,
  onContinue,
  onLogin,
  onRegister,
  onChangePassword,
  onLogout,
  message
}: {
  currentUser: User | null;
  onContinue: () => void;
  onLogin: (username: string, password: string) => Promise<void>;
  onRegister: (input: { username: string; password: string; display_name: string; email: string }) => Promise<void>;
  onChangePassword: (input: { current_password: string; new_password: string; confirm_password: string }) => Promise<void>;
  onLogout: () => Promise<void>;
  message: string;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("local-admin");
  const [password, setPassword] = useState("");
  const [passwordPanelOpen, setPasswordPanelOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [passwordBusy, setPasswordBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") {
        await onLogin(username.trim(), password);
      } else {
        await onRegister({
          username: username.trim(),
          password,
          display_name: displayName.trim() || username.trim(),
          email: email.trim()
        });
        setMode("login");
        setPassword("");
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setBusy(false);
    }
  }

  async function submitPasswordChange(event: React.FormEvent) {
    event.preventDefault();
    setPasswordBusy(true);
    setError("");
    try {
      await onChangePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordPanelOpen(false);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setPasswordBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-brand">
          <Zap className="brand-icon" size={30} fill="currentColor" />
          <div>
            <strong>Jolt CodeReview</strong>
            <span>登录后进入你的项目空间</span>
          </div>
        </div>
        <div className="auth-tabs" role="tablist">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>登录</button>
          <button type="button" className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}>注册</button>
        </div>
        {currentUser && (
          <div className="auth-current-user">
            <div>
              <span>当前已登录</span>
              <strong>{currentUser.display_name || currentUser.username}</strong>
              <em>{currentUser.username}</em>
            </div>
            <button type="button" onClick={onContinue}>进入项目空间</button>
            <button type="button" className="ghost" onClick={onLogout}>切换账号</button>
          </div>
        )}
        <form className="auth-form" onSubmit={submit}>
          <label>
            <span>用户名</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
          </label>
          {mode === "register" && (
            <>
              <label>
                <span>显示名</span>
                <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="默认使用用户名" />
              </label>
              <label>
                <span>邮箱</span>
                <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="可选" />
              </label>
            </>
          )}
          <label>
            <span>密码</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "login" ? "请输入密码" : "至少 6 位"} />
          </label>
          {(error || message) && <p className={error ? "form-error" : "auth-message"}>{error || message}</p>}
          <button type="submit" disabled={busy}>
            {busy ? "处理中..." : mode === "login" ? "登录" : "注册账号"}
          </button>
          {mode === "login" && (
            <button
              type="button"
              className="auth-link-button"
              onClick={() => {
                if (!currentUser) {
                  setError("请先登录后再修改密码");
                  return;
                }
                setError("");
                setPasswordPanelOpen((value) => !value);
              }}
            >
              修改密码
            </button>
          )}
        </form>
        {mode === "login" && passwordPanelOpen && currentUser && (
          <form className="auth-password-form" onSubmit={submitPasswordChange}>
            <label>
              <span>当前密码</span>
              <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
            </label>
            <label>
              <span>新密码</span>
              <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="至少 6 位" />
            </label>
            <label>
              <span>确认新密码</span>
              <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
            </label>
            <button type="submit" disabled={passwordBusy}>{passwordBusy ? "保存中..." : "保存新密码"}</button>
          </form>
        )}
        <p className="auth-hint">本机默认 root 账号：local-admin。生产部署时请先修改初始化密码和密码策略。</p>
      </section>
    </main>
  );
}

export function PublishResultModal({ notice, onClose }: { notice: PublishResultNotice; onClose: () => void }) {
  const success = notice.status === "success";
  const skippedCount = Number(notice.skippedCount || 0);
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={notice.title} onClick={onClose}>
      <section className={`publish-result-modal ${notice.status}`} onClick={(event) => event.stopPropagation()}>
        <div className="publish-result-icon">
          {success ? <Check /> : <Circle />}
        </div>
        <div className="publish-result-content">
          <strong>{notice.title}</strong>
          <p>{notice.message}</p>
          <div className="publish-result-counts" aria-label="发布结果统计">
            <span><b>{notice.publishedCount}</b> 成功</span>
            {skippedCount > 0 && <span className="skipped"><b>{skippedCount}</b> 已提交过</span>}
            <span><b>{notice.requestedCount}</b> 选中</span>
          </div>
          {notice.detail && <span className="publish-result-detail">{notice.detail}</span>}
          <button type="button" onClick={onClose}>知道了</button>
        </div>
      </section>
    </div>
  );
}

