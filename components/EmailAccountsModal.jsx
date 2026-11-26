// react/components/EmailAccountsModal.jsx
//
// The Email Accounts panel: the user adds the mailboxes Boundary's local
// agents may use, picks which one is current, and removes old ones.
// Authorization codes are sent to the server once, stored encrypted, and
// never shown again.

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";

const PROVIDERS = [
  { id: "qq", name: "QQ Mail", domains: ["qq.com", "foxmail.com", "vip.qq.com"] },
  { id: "163", name: "163 Mail", domains: ["163.com"] },
  { id: "126", name: "126 Mail", domains: ["126.com"] },
  { id: "yeah", name: "Yeah.net", domains: ["yeah.net"] },
  { id: "gmail", name: "Gmail", domains: ["gmail.com", "googlemail.com"] },
  { id: "exmail", name: "Tencent Exmail (company)", domains: [] },
  { id: "sina", name: "Sina Mail", domains: ["sina.com", "sina.cn"] },
  { id: "139", name: "139 Mail", domains: ["139.com"] },
  { id: "aliyun", name: "Aliyun Mail", domains: ["aliyun.com"] },
  { id: "outlook", name: "Outlook / Microsoft 365", domains: ["outlook.com", "hotmail.com", "live.com", "msn.com"] },
  { id: "custom", name: "Other (enter servers)", domains: [] },
];

const GUIDES = {
  qq: "In QQ Mail on the web: 设置 → 账号 → POP3/IMAP/SMTP服务 → 开启. QQ sends an SMS check, then shows a 16-letter 授权码. Paste that here, not your QQ password.",
  "163": "In 163 Mail on the web: 设置 → POP3/SMTP/IMAP → turn on IMAP/SMTP服务. Confirm by SMS, then copy the 授权码 shown.",
  "126": "In 126 Mail on the web: 设置 → POP3/SMTP/IMAP → turn on IMAP/SMTP服务, then copy the 授权码 shown.",
  yeah: "In Yeah.net on the web: 设置 → POP3/SMTP/IMAP → turn on IMAP/SMTP服务, then copy the 授权码.",
  gmail: "Turn on 2-Step Verification in your Google Account, then go to Security → App passwords, create one for \"Boundary\", and paste the 16-letter password here.",
  exmail: "Your company mail admin must allow IMAP/SMTP. In Exmail: 设置 → 客户端设置 → enable IMAP/SMTP, then generate a 客户端专用密码 and paste it here.",
  sina: "In Sina Mail: 设置 → 客户端POP/IMAP/SMTP → turn on IMAP/SMTP, then copy the 授权码.",
  "139": "In 139 Mail: 设置 → 客户端设置 → turn on IMAP/SMTP, then copy the authorization code.",
  aliyun: "In Aliyun Mail: 设置 → 客户端设置 → enable IMAP/SMTP. Use the client password shown there.",
  outlook: "Microsoft accounts work through the classic Outlook desktop app on your computer, with this exact address set up in it. No code is needed.",
  custom: "Enter your mail provider's IMAP and SMTP servers and the password or app password it gives mail apps.",
};

function guessProvider(address) {
  const domain = (address.split("@")[1] || "").toLowerCase();
  const match = PROVIDERS.find((p) => p.domains.includes(domain));
  return match ? match.id : "";
}

const emptyForm = {
  address: "",
  provider: "",
  auth_code: "",
  label: "",
  display_name: "",
  imap_host: "",
  imap_port: "993",
  smtp_host: "",
  smtp_port: "465",
};

export default function EmailAccountsModal({ onClose }) {
  const { getToken } = useAuth();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8770";

  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [providerTouched, setProviderTouched] = useState(false);

  const call = useCallback(
    async (path, options = {}) => {
      const token = await getToken();
      const response = await fetch(`${apiUrl}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...(options.headers || {}),
        },
      });
      let data = {};
      try {
        data = await response.json();
      } catch (e) {
        data = {};
      }
      if (!response.ok || data.success === false) {
        throw new Error(data.error || `Request failed (${response.status})`);
      }
      return data;
    },
    [apiUrl, getToken]
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await call("/api/mail-accounts");
      setAccounts(data.accounts || []);
      if (!data.accounts || data.accounts.length === 0) setShowForm(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [call]);

  useEffect(() => {
    load();
  }, [load]);

  const updateField = (field, value) => {
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === "address" && !providerTouched) {
        next.provider = guessProvider(value);
      }
      return next;
    });
  };

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const addAccount = (e) => {
    e.preventDefault();
    if (!form.address.includes("@")) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!form.provider) {
      setError("Please choose your mail provider.");
      return;
    }
    if (form.provider !== "outlook" && !form.auth_code.trim()) {
      setError("Please paste the authorization code (授权码) or app password.");
      return;
    }
    run(async () => {
      await call("/api/mail-accounts", {
        method: "POST",
        body: JSON.stringify(form),
      });
      setForm(emptyForm);
      setProviderTouched(false);
      setShowForm(false);
    });
  };

  const makeCurrent = (id) =>
    run(() => call(`/api/mail-accounts/${id}/current`, { method: "POST" }));

  const remove = (account) => {
    if (!window.confirm(`Remove ${account.address} from Boundary? Its saved code is deleted too.`)) return;
    run(() => call(`/api/mail-accounts/${account.id}`, { method: "DELETE" }));
  };

  const providerName = (id) => (PROVIDERS.find((p) => p.id === id) || {}).name || id;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-8 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-start justify-between mb-2">
          <h2 className="text-2xl font-bold">📮 Email Accounts</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">
            ×
          </button>
        </div>
        <p className="text-gray-600 mb-6">
          Boundary&apos;s local agents read, draft and send email from the <strong>current</strong> account
          below, through the bridge on your computer. Add each mailbox you want them to use, and switch
          the current one at any time.
        </p>

        {error && (
          <div className="mb-4 p-3 rounded bg-red-50 text-red-700 border border-red-200 text-sm">{error}</div>
        )}

        {loading ? (
          <p className="text-gray-500">Loading accounts...</p>
        ) : (
          <div className="space-y-2 mb-6">
            {accounts.length === 0 && (
              <p className="text-gray-500 text-sm">No email accounts yet. Add one below.</p>
            )}
            {accounts.map((account) => (
              <div
                key={account.id}
                className={`flex items-center justify-between p-3 rounded border ${
                  account.is_current ? "border-blue-500 bg-blue-50" : "border-gray-200"
                }`}
              >
                <div>
                  <div className="font-medium">
                    {account.address}
                    {account.label ? <span className="text-gray-500 font-normal"> · {account.label}</span> : null}
                  </div>
                  <div className="text-sm text-gray-500">{providerName(account.provider)}</div>
                </div>
                <div className="flex items-center gap-2">
                  {account.is_current ? (
                    <span className="px-3 py-1 text-sm rounded bg-blue-600 text-white">Current</span>
                  ) : (
                    <button
                      disabled={busy}
                      onClick={() => makeCurrent(account.id)}
                      className="px-3 py-1 text-sm rounded bg-gray-100 hover:bg-gray-200 disabled:opacity-50"
                    >
                      Use this one
                    </button>
                  )}
                  <button
                    disabled={busy}
                    onClick={() => remove(account)}
                    className="px-3 py-1 text-sm rounded text-red-600 hover:bg-red-50 disabled:opacity-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!showForm ? (
          <button
            onClick={() => setShowForm(true)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded"
          >
            + Add an email account
          </button>
        ) : (
          <form onSubmit={addAccount} className="space-y-4 border-t pt-6">
            <h3 className="text-lg font-semibold">Add an email account</h3>

            <div>
              <label className="block text-sm font-medium mb-1">Email address</label>
              <input
                type="email"
                value={form.address}
                onChange={(e) => updateField("address", e.target.value.trim())}
                placeholder="you@qq.com"
                className="w-full border rounded px-3 py-2"
                autoComplete="off"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Mail provider</label>
              <select
                value={form.provider}
                onChange={(e) => {
                  setProviderTouched(true);
                  updateField("provider", e.target.value);
                }}
                className="w-full border rounded px-3 py-2 bg-white"
              >
                <option value="">Choose...</option>
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            {form.provider && (
              <div className="bg-gray-100 p-4 rounded text-sm text-gray-700">{GUIDES[form.provider]}</div>
            )}

            {form.provider === "custom" && (
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-sm font-medium mb-1">IMAP server</label>
                  <input
                    value={form.imap_host}
                    onChange={(e) => updateField("imap_host", e.target.value.trim())}
                    placeholder="imap.example.com"
                    className="w-full border rounded px-3 py-2"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Port</label>
                  <input
                    value={form.imap_port}
                    onChange={(e) => updateField("imap_port", e.target.value.trim())}
                    className="w-full border rounded px-3 py-2"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-sm font-medium mb-1">SMTP server</label>
                  <input
                    value={form.smtp_host}
                    onChange={(e) => updateField("smtp_host", e.target.value.trim())}
                    placeholder="smtp.example.com"
                    className="w-full border rounded px-3 py-2"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Port</label>
                  <input
                    value={form.smtp_port}
                    onChange={(e) => updateField("smtp_port", e.target.value.trim())}
                    className="w-full border rounded px-3 py-2"
                  />
                </div>
              </div>
            )}

            {form.provider && form.provider !== "outlook" && (
              <div>
                <label className="block text-sm font-medium mb-1">Authorization code (授权码) or app password</label>
                <input
                  type="password"
                  value={form.auth_code}
                  onChange={(e) => updateField("auth_code", e.target.value)}
                  className="w-full border rounded px-3 py-2"
                  autoComplete="new-password"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Stored encrypted and never shown again. You can cancel the code in your mailbox settings at
                  any time.
                </p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium mb-1">Label (optional)</label>
                <input
                  value={form.label}
                  onChange={(e) => updateField("label", e.target.value)}
                  placeholder="Work, Personal..."
                  className="w-full border rounded px-3 py-2"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Name on emails (optional)</label>
                <input
                  value={form.display_name}
                  onChange={(e) => updateField("display_name", e.target.value)}
                  placeholder="Your name"
                  className="w-full border rounded px-3 py-2"
                />
              </div>
            </div>

            <div className="flex justify-end gap-3">
              {accounts.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    setShowForm(false);
                    setForm(emptyForm);
                    setProviderTouched(false);
                  }}
                  className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded"
                >
                  Cancel
                </button>
              )}
              <button
                type="submit"
                disabled={busy}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded disabled:opacity-50"
              >
                {busy ? "Saving..." : "Save account"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}