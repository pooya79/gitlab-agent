import type { CreateClientConfig } from "@/client/client.gen";
import { env } from "@/env";
import { getAdminAccessToken } from "@/lib/admin-auth/tokens";
import { getAccessToken } from "@/lib/auth/tokens";

export const createClientConfig: CreateClientConfig = (config) => ({
    ...config,
    baseUrl: env.BACKEND_URL,
    // Admin pages live entirely under /admin and use a separate token realm;
    // pick the admin token there, the regular user token everywhere else.
    auth: () =>
        (typeof window !== "undefined" &&
        window.location.pathname.startsWith("/admin")
            ? getAdminAccessToken()
            : getAccessToken()) ?? "",
});
