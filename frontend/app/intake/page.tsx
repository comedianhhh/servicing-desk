"use client";

// Mailroom. A scan, a PDF, or pasted text becomes a case. The original is archived before anything is
// derived from it; the response says which extractor produced the text so the operator knows what to trust.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { OperatorPicker, useActingOperator } from "@/app/components/operator-picker";
import { JSON_HEADERS, asOperator } from "@/app/components/use-operator";

export default function IntakePage() {
  const router = useRouter();
  const operator = useActingOperator();
  const today = new Date().toISOString().slice(0, 10);
  const [channel, setChannel] = useState("mail");
  const [receivedOn, setReceivedOn] = useState(today);
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit() {
    setBusy(true);
    setMsg(null);
    let r: Response;
    if (file) {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("channel", channel);
      fd.append("received_on", receivedOn);
      r = await fetch("/api/desk/intake/document", { method: "POST", headers: asOperator(operator), body: fd });
    } else {
      r = await fetch("/api/desk/intake", { method: "POST", headers: asOperator(operator, JSON_HEADERS), body: JSON.stringify({ body: text, channel, received_on: receivedOn }) });
    }
    const j = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) {
      setMsg({ ok: false, text: `${r.status}: ${typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j)}` });
      return;
    }
    setMsg({ ok: true, text: j.created ? `case opened${j.engine ? ` · text via ${j.engine}, ${j.pages} page(s)` : ""}` : "duplicate of an existing case — no new case opened" });
    setTimeout(() => router.push(`/cases/${j.case_id}`), 600);
  }

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-lg font-semibold">Intake</h1>
      <div className="bg-white border border-stone-200 rounded p-4 space-y-3 text-sm">
        <div className="flex gap-4">
          <label className="flex items-center gap-2">
            <span className="text-stone-500">Channel</span>
            <select className="border rounded px-2 py-1" value={channel} onChange={(e) => setChannel(e.target.value)}>
              {["mail", "email", "portal", "fax"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-stone-500">Received on</span>
            <input type="date" className="border rounded px-2 py-1" value={receivedOn} onChange={(e) => setReceivedOn(e.target.value)} />
          </label>
          <label className="flex items-center gap-2">
            <span className="text-stone-500">Acting as</span>
            <OperatorPicker className="px-2 py-1" />
          </label>
        </div>
        <div>
          <div className="text-stone-500 mb-1">Scan, PDF, or image</div>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.txt,application/pdf,image/*,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="text-xs text-stone-400 mt-1">Archived byte-for-byte; text comes from the PDF text layer when there is one, otherwise from OCR.</div>
        </div>
        <div className="text-stone-400 text-xs">— or —</div>
        <div>
          <div className="text-stone-500 mb-1">Paste the letter</div>
          <textarea className="border rounded w-full h-40 px-2 py-1 font-sans" value={text} onChange={(e) => setText(e.target.value)} disabled={!!file} />
        </div>
        {msg && <div className={`rounded px-2 py-1 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`}>{msg.text}</div>}
        <button disabled={busy || (!file && text.trim().length === 0)} onClick={submit} className="rounded bg-stone-800 text-white px-3 py-1.5 disabled:opacity-50">
          {busy ? "Working…" : "Open case"}
        </button>
      </div>
    </div>
  );
}
