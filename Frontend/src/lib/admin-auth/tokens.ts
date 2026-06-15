/**
 * Admin token management — mirrors lib/auth/tokens.ts but uses separate
 * localStorage keys so the admin realm is independent of regular user auth.
 */

const ADMIN_ACCESS_TOKEN_KEY = "admin_access_token";
const ADMIN_REFRESH_TOKEN_KEY = "admin_refresh_token";
const ADMIN_TOKEN_EXPIRY_KEY = "admin_token_expiry";

export interface AdminAuthTokens {
    accessToken: string;
    refreshToken: string;
    expiresIn: number; // in seconds
}

export function setAdminAuthTokens(tokens: AdminAuthTokens): void {
    if (typeof window === "undefined") return;

    try {
        localStorage.setItem(ADMIN_ACCESS_TOKEN_KEY, tokens.accessToken);
        localStorage.setItem(ADMIN_REFRESH_TOKEN_KEY, tokens.refreshToken);
        const expiryTime = Date.now() + tokens.expiresIn * 1000;
        localStorage.setItem(ADMIN_TOKEN_EXPIRY_KEY, expiryTime.toString());
    } catch (error) {
        console.error("Error saving admin auth tokens:", error);
    }
}

export function getAdminAccessToken(): string | null {
    if (typeof window === "undefined") return null;
    try {
        return localStorage.getItem(ADMIN_ACCESS_TOKEN_KEY);
    } catch (error) {
        console.error("Error getting admin access token:", error);
        return null;
    }
}

export function getAdminRefreshToken(): string | null {
    if (typeof window === "undefined") return null;
    try {
        return localStorage.getItem(ADMIN_REFRESH_TOKEN_KEY);
    } catch (error) {
        console.error("Error getting admin refresh token:", error);
        return null;
    }
}

export function clearAdminAuthTokens(): void {
    if (typeof window === "undefined") return;
    try {
        localStorage.removeItem(ADMIN_ACCESS_TOKEN_KEY);
        localStorage.removeItem(ADMIN_REFRESH_TOKEN_KEY);
        localStorage.removeItem(ADMIN_TOKEN_EXPIRY_KEY);
    } catch (error) {
        console.error("Error clearing admin auth tokens:", error);
    }
}

export function isAdminTokenExpired(bufferSeconds: number = 60): boolean {
    if (typeof window === "undefined") return true;
    try {
        const expiryTime = localStorage.getItem(ADMIN_TOKEN_EXPIRY_KEY);
        if (!expiryTime) return true;
        return Date.now() >= Number(expiryTime) - bufferSeconds * 1000;
    } catch (error) {
        console.error("Error checking admin token expiry:", error);
        return true;
    }
}

export function isAdminAuthenticated(): boolean {
    return !!(getAdminAccessToken() && getAdminRefreshToken());
}
