/**
 * Authentication Provider
 * Sets up automatic token refresh for the entire application
 */

"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { setupTokenRefresh, clearAuthTokens } from "./index";

interface AuthProviderProps {
    children: React.ReactNode;
}

/**
 * Provider component that sets up automatic token refresh
 * Add this to your root layout to enable auto-refresh across the app
 */
export function AuthProvider({ children }: AuthProviderProps) {
    const router = useRouter();
    const pathname = usePathname();

    useEffect(() => {
        // The /admin/* pages are a separate auth realm (see lib/admin-auth).
        // The user-realm refresh loop must not run there, or it bounces an
        // admin-only session to /login?redirect=/admin/... on its interval tick.
        if (pathname.startsWith("/admin")) {
            return;
        }

        // Set up automatic token refresh
        const cleanup = setupTokenRefresh(
            () => {
                console.log("✅ Token refreshed successfully");
            },
            () => {
                console.error("❌ Token refresh failed");
                clearAuthTokens();

                // Don't redirect if already on login pages
                if (!pathname.startsWith("/login")) {
                    router.push(
                        `/login?redirect=${encodeURIComponent(pathname)}`,
                    );
                }
            },
        );

        return cleanup;
    }, [router, pathname]);

    return <>{children}</>;
}
