"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { adminLogoutApiV1AdminLogoutPost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import {
    AdminProtectedRoute,
    clearAdminAuthTokens,
    getAdminRefreshToken,
    setupAdminTokenRefresh,
} from "@/lib/admin-auth";

// Tabs are intentionally data-driven so more admin sections can be added later.
const ADMIN_TABS = [
    { href: "/admin/settings/gitlab", label: "GitLab Settings" },
];

function AdminChrome({ children }: { children: React.ReactNode }) {
    const pathname = usePathname();
    const router = useRouter();

    useEffect(() => {
        const cleanup = setupAdminTokenRefresh(() => {
            clearAdminAuthTokens();
            router.push("/admin/login");
        });
        return cleanup;
    }, [router]);

    const handleLogout = async () => {
        const refreshToken = getAdminRefreshToken();
        if (refreshToken) {
            try {
                await adminLogoutApiV1AdminLogoutPost({
                    body: { refresh_token: refreshToken },
                });
            } catch {
                // ignore — clear locally regardless
            }
        }
        clearAdminAuthTokens();
        router.push("/admin/login");
    };

    return (
        <div className="min-h-screen">
            <header className="border-b bg-background/95 backdrop-blur supports-backdrop-filter:bg-background/60">
                <div className="container mx-auto flex h-16 items-center justify-between px-8">
                    <h1 className="text-xl font-bold">Admin</h1>
                    <Button variant="ghost" onClick={handleLogout}>
                        <LogOut className="mr-2 h-4 w-4" />
                        Log out
                    </Button>
                </div>
            </header>
            <div className="container mx-auto flex gap-8 px-8 py-8">
                <nav className="w-56 shrink-0 space-y-1">
                    {ADMIN_TABS.map((tab) => {
                        const active = pathname.startsWith(tab.href);
                        return (
                            <Link
                                key={tab.href}
                                href={tab.href}
                                className={`block rounded-md px-3 py-2 text-sm ${
                                    active
                                        ? "bg-muted font-medium"
                                        : "text-muted-foreground hover:bg-muted/50"
                                }`}
                            >
                                {tab.label}
                            </Link>
                        );
                    })}
                </nav>
                <main className="flex-1">{children}</main>
            </div>
        </div>
    );
}

export default function AdminLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const pathname = usePathname();

    // The login page must render outside the protected chrome.
    if (pathname === "/admin/login") {
        return <>{children}</>;
    }

    return (
        <AdminProtectedRoute>
            <AdminChrome>{children}</AdminChrome>
        </AdminProtectedRoute>
    );
}
