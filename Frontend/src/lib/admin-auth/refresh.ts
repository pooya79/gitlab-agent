/**
 * Admin token refresh — mirrors lib/auth/refresh.ts against the /admin endpoints.
 */

import { adminRefreshApiV1AdminRefreshPost } from "@/client/sdk.gen";
import {
    clearAdminAuthTokens,
    getAdminRefreshToken,
    isAdminTokenExpired,
    setAdminAuthTokens,
} from "./tokens";

let refreshPromise: Promise<boolean> | null = null;

export async function refreshAdminAccessToken(): Promise<boolean> {
    if (refreshPromise) {
        return refreshPromise;
    }

    refreshPromise = (async () => {
        try {
            const refreshToken = getAdminRefreshToken();
            if (!refreshToken) {
                clearAdminAuthTokens();
                return false;
            }

            const response = await adminRefreshApiV1AdminRefreshPost({
                body: { refresh_token: refreshToken },
            });

            if (response.error || !response.data) {
                clearAdminAuthTokens();
                return false;
            }

            setAdminAuthTokens({
                accessToken: response.data.access_token,
                refreshToken: response.data.refresh_token,
                expiresIn: response.data.expires_in,
            });
            return true;
        } catch (error) {
            console.error("Exception while refreshing admin token:", error);
            clearAdminAuthTokens();
            return false;
        } finally {
            refreshPromise = null;
        }
    })();

    return refreshPromise;
}

export async function ensureValidAdminToken(): Promise<boolean> {
    if (!isAdminTokenExpired()) {
        return true;
    }
    return await refreshAdminAccessToken();
}

export function setupAdminTokenRefresh(
    onRefreshFailed?: () => void,
): () => void {
    const intervalId = setInterval(async () => {
        if (isAdminTokenExpired(300)) {
            const success = await refreshAdminAccessToken();
            if (!success && onRefreshFailed) {
                onRefreshFailed();
            }
        }
    }, 60000);

    return () => clearInterval(intervalId);
}
