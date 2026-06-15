"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
    getGitlabSettingsApiV1AdminSettingsGitlabGet,
    patchGitlabSettingsApiV1AdminSettingsGitlabPatch,
} from "@/client/sdk.gen";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function GitlabSettingsPage() {
    const [base, setBase] = useState("");
    const [clientId, setClientId] = useState("");
    const [clientSecret, setClientSecret] = useState("");
    const [sslVerify, setSslVerify] = useState(true);
    const [secretSet, setSecretSet] = useState(false);

    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            const response =
                await getGitlabSettingsApiV1AdminSettingsGitlabGet();
            if (response.error || !response.data) {
                setLoadError("Failed to load GitLab settings.");
                return;
            }
            setBase(response.data.gitlab_base ?? "");
            setClientId(response.data.gitlab_client_id ?? "");
            setSslVerify(response.data.gitlab_webhook_ssl_verify);
            setSecretSet(response.data.gitlab_client_secret_set);
            setClientSecret("");
        } catch {
            setLoadError("Failed to load GitLab settings.");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const handleSave = async () => {
        setSaving(true);
        setSaveError(null);
        setSaveSuccess(null);
        try {
            const response =
                await patchGitlabSettingsApiV1AdminSettingsGitlabPatch({
                    body: {
                        gitlab_base: base || null,
                        gitlab_client_id: clientId || null,
                        // Empty means "keep existing"; backend ignores blank secrets.
                        gitlab_client_secret: clientSecret || null,
                        gitlab_webhook_ssl_verify: sslVerify,
                    },
                });

            if (response.error || !response.data) {
                setSaveError("Failed to save GitLab settings.");
                return;
            }

            setSecretSet(response.data.gitlab_client_secret_set);
            setClientSecret("");
            setSaveSuccess("GitLab settings saved.");
        } catch {
            setSaveError("Failed to save GitLab settings.");
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin" />
            </div>
        );
    }

    return (
        <div className="max-w-2xl space-y-6">
            <div>
                <h2 className="text-2xl font-bold">GitLab Settings</h2>
                <p className="text-muted-foreground">
                    These OAuth settings replace the GitLab environment
                    variables. Until they are set, normal user sign-in is
                    disabled.
                </p>
            </div>

            {loadError && (
                <Alert variant="destructive">
                    <AlertDescription>{loadError}</AlertDescription>
                </Alert>
            )}

            <Card>
                <CardHeader>
                    <CardTitle>OAuth application</CardTitle>
                    <CardDescription>
                        From your GitLab instance&apos;s OAuth application
                        settings.
                    </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="space-y-2">
                        <Label htmlFor="base">GitLab base URL</Label>
                        <Input
                            id="base"
                            placeholder="https://gitlab.com"
                            value={base}
                            onChange={(e) => setBase(e.target.value)}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label htmlFor="client-id">Client ID</Label>
                        <Input
                            id="client-id"
                            value={clientId}
                            onChange={(e) => setClientId(e.target.value)}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label htmlFor="client-secret">Client secret</Label>
                        <Input
                            id="client-secret"
                            type="password"
                            placeholder={
                                secretSet
                                    ? "•••••••• (leave blank to keep)"
                                    : "Not set"
                            }
                            value={clientSecret}
                            onChange={(e) => setClientSecret(e.target.value)}
                        />
                    </div>
                    <div className="flex items-center gap-2">
                        <input
                            id="ssl-verify"
                            type="checkbox"
                            className="h-4 w-4"
                            checked={sslVerify}
                            onChange={(e) => setSslVerify(e.target.checked)}
                        />
                        <Label htmlFor="ssl-verify">
                            Verify SSL on bot webhooks
                        </Label>
                    </div>
                </CardContent>
            </Card>

            {saveError && (
                <Alert variant="destructive">
                    <AlertDescription>{saveError}</AlertDescription>
                </Alert>
            )}
            {saveSuccess && (
                <Alert>
                    <AlertDescription>{saveSuccess}</AlertDescription>
                </Alert>
            )}

            <Button onClick={handleSave} disabled={saving}>
                {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                    "Save settings"
                )}
            </Button>
        </div>
    );
}
