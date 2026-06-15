/**
 * Admin protected route wrapper — redirects to /admin/login when not authed.
 */

"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ensureValidAdminToken } from "./refresh";
import { isAdminAuthenticated } from "./tokens";

interface AdminProtectedRouteProps {
    children: React.ReactNode;
    fallback?: React.ReactNode;
}

export function AdminProtectedRoute({
    children,
    fallback,
}: AdminProtectedRouteProps) {
    const router = useRouter();
    const [isChecking, setIsChecking] = useState(true);
    const [isAuthorized, setIsAuthorized] = useState(false);

    useEffect(() => {
        const checkAuth = async () => {
            if (!isAdminAuthenticated()) {
                router.push("/admin/login");
                return;
            }

            const isValid = await ensureValidAdminToken();
            if (!isValid) {
                router.push("/admin/login");
                return;
            }

            setIsAuthorized(true);
            setIsChecking(false);
        };

        checkAuth();
    }, [router]);

    if (isChecking) {
        return (
            fallback || (
                <div className="flex min-h-screen items-center justify-center">
                    <div className="text-center">
                        <div className="mb-4 inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent"></div>
                        <p className="text-lg">Loading...</p>
                    </div>
                </div>
            )
        );
    }

    return isAuthorized ? <>{children}</> : null;
}
