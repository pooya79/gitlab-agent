"use client";

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import {
    createContext,
    type ReactNode,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { cn } from "@/lib/utils";

export type ToastVariant = "default" | "success" | "error" | "warning";

export interface ToastOptions {
    title: string;
    description?: string;
    variant?: ToastVariant;
    /** Auto-dismiss delay in ms. Defaults to 5000. */
    duration?: number;
}

interface ToastItem extends ToastOptions {
    id: number;
}

interface ToastContextValue {
    toast: (options: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
    const ctx = useContext(ToastContext);
    if (!ctx) {
        throw new Error("useToast must be used within a <ToastProvider>");
    }
    return ctx;
}

const variantStyles: Record<ToastVariant, string> = {
    default: "border-border",
    success: "border-green-600/40",
    error: "border-destructive/50",
    warning: "border-yellow-600/40",
};

const variantIcon: Record<ToastVariant, ReactNode> = {
    default: <Info className="h-5 w-5 text-foreground" />,
    success: <CheckCircle2 className="h-5 w-5 text-green-600" />,
    error: <XCircle className="h-5 w-5 text-destructive" />,
    warning: <AlertTriangle className="h-5 w-5 text-yellow-600" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<ToastItem[]>([]);
    const idRef = useRef(0);
    const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(
        new Map(),
    );

    const dismiss = useCallback((id: number) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
        const timer = timersRef.current.get(id);
        if (timer) {
            clearTimeout(timer);
            timersRef.current.delete(id);
        }
    }, []);

    const toast = useCallback(
        (options: ToastOptions) => {
            idRef.current += 1;
            const id = idRef.current;
            const duration = options.duration ?? 5000;
            setToasts((prev) => [
                ...prev,
                { variant: "default", ...options, id },
            ]);
            const timer = setTimeout(() => dismiss(id), duration);
            timersRef.current.set(id, timer);
        },
        [dismiss],
    );

    // Clear any pending timers on unmount.
    useEffect(() => {
        const timers = timersRef.current;
        return () => {
            for (const timer of timers.values()) {
                clearTimeout(timer);
            }
            timers.clear();
        };
    }, []);

    const value = useMemo(() => ({ toast }), [toast]);

    return (
        <ToastContext.Provider value={value}>
            {children}
            <div className="pointer-events-none fixed bottom-0 right-0 z-[100] flex w-full max-w-sm flex-col gap-2 p-4">
                {toasts.map((t) => {
                    const variant = t.variant ?? "default";
                    return (
                        <div
                            key={t.id}
                            aria-live="polite"
                            className={cn(
                                "pointer-events-auto flex items-start gap-3 rounded-lg border bg-card p-4 text-card-foreground shadow-lg animate-in fade-in slide-in-from-right-full",
                                variantStyles[variant],
                            )}
                        >
                            <span className="mt-0.5 shrink-0">
                                {variantIcon[variant]}
                            </span>
                            <div className="min-w-0 flex-1">
                                <p className="text-sm font-medium">{t.title}</p>
                                {t.description && (
                                    <p className="mt-1 whitespace-pre-line break-words text-sm text-muted-foreground">
                                        {t.description}
                                    </p>
                                )}
                            </div>
                            <button
                                type="button"
                                onClick={() => dismiss(t.id)}
                                className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
                                aria-label="Dismiss notification"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                    );
                })}
            </div>
        </ToastContext.Provider>
    );
}
