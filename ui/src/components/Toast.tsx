"use client";

import { useEffect } from "react";

export interface ToastState {
  type: "success" | "error";
  message: string;
}

interface ToastProps {
  toast: ToastState | null;
  onDismiss: () => void;
}

export default function Toast({ toast, onDismiss }: ToastProps) {
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(onDismiss, toast.type === "error" ? 6000 : 4000);
    return () => clearTimeout(timer);
  }, [toast, onDismiss]);

  if (!toast) return null;

  const colors =
    toast.type === "error"
      ? "bg-red-50 border-red-200 text-red-700"
      : "bg-green-50 border-green-200 text-green-700";

  return (
    <div className={`fixed top-4 right-4 z-50 max-w-sm border rounded-lg shadow-lg px-4 py-3 ${colors}`}>
      <div className="flex items-start gap-2">
        <span className="text-sm flex-1">{toast.message}</span>
        <button
          onClick={onDismiss}
          className="text-current opacity-50 hover:opacity-100 text-lg leading-none"
        >
          &times;
        </button>
      </div>
    </div>
  );
}
