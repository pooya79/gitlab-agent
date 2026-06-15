"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { gitlabLoginApiV1AuthGitlabLoginGet } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { isAuthenticated } from "@/lib/auth";

function LoginContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const [loginError, setLoginError] = useState<string | null>(null);

    useEffect(() => {
        // Check if user is already authenticated
        if (isAuthenticated()) {
            const redirectTo = searchParams.get("redirect") || "/dashboard";
            console.log(
                "User already authenticated, redirecting to:",
                redirectTo,
            );
            router.push(redirectTo);
        }
    }, [router, searchParams]);

    const handleGitlabSignIn = async () => {
        setLoginError(null);
        const { data, error, response } =
            await gitlabLoginApiV1AuthGitlabLoginGet();
        if (error) {
            if (response?.status === 503) {
                setLoginError(
                    "GitLab sign-in isn't configured yet — contact your administrator.",
                );
            } else {
                setLoginError("Could not start GitLab sign-in. Try again.");
            }
            return;
        }
        if (data && data.url) {
            window.location.href = data.url;
        } else {
            setLoginError("No sign-in URL received. Try again.");
        }
    };

    return (
        <div className="flex h-screen items-center justify-center">
            <Card className="w-[360px] p-4 text-center shadow-md">
                <CardHeader>
                    <CardTitle className="text-xl font-semibold">
                        Sign in
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <Button
                        className="w-full flex items-center justify-center gap-2 cursor-pointer"
                        onClick={handleGitlabSignIn}
                    >
                        <svg
                            role="img"
                            viewBox="0 0 24 24"
                            xmlns="http://www.w3.org/2000/svg"
                            className="h-5 w-5 text-[#fc6d26]"
                            fill="currentColor"
                        >
                            <title>GitLab</title>
                            <path d="m23.6004 9.5927-.0337-.0862L20.3.9814a.851.851 0 0 0-.3362-.405.8748.8748 0 0 0-.9997.0539.8748.8748 0 0 0-.29.4399l-2.2055 6.748H7.5375l-2.2057-6.748a.8573.8573 0 0 0-.29-.4412.8748.8748 0 0 0-.9997-.0537.8585.8585 0 0 0-.3362.4049L.4332 9.5015l-.0325.0862a6.0657 6.0657 0 0 0 2.0119 7.0105l.0113.0087.03.0213 4.976 3.7264 2.462 1.8633 1.4995 1.1321a1.0085 1.0085 0 0 0 1.2197 0l1.4995-1.1321 2.4619-1.8633 5.006-3.7489.0125-.01a6.0682 6.0682 0 0 0 2.0094-7.003z" />
                        </svg>
                        Sign in with GitLab
                    </Button>
                    {loginError && (
                        <p className="mt-3 text-sm text-destructive">
                            {loginError}
                        </p>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}

export default function LoginPage() {
    return (
        <Suspense
            fallback={
                <div className="flex h-screen items-center justify-center">
                    <Card className="w-[360px] p-4 text-center shadow-md">
                        <CardHeader>
                            <CardTitle className="text-xl font-semibold">
                                Sign in
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="flex items-center justify-center">
                                <div className="h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent"></div>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            }
        >
            <LoginContent />
        </Suspense>
    );
}
