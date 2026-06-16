"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
    createBotApiV1BotsPost,
    createNewBotAccessTokenApiV1BotsBotIdNewAccessTokenPatch,
    deleteBotApiV1BotsBotIdDelete,
    getBotStatusApiV1BotsBotIdStatusGet,
    listBotsApiV1BotsGet,
    listGitlabProjectsApiV1GitlabProjectsGet,
    toggleBotActiveApiV1BotsBotIdToggleActivePatch,
} from "@/client/sdk.gen";
import {
    type Bot,
    type BotStatus,
    BotsTable,
    type BotsTableHandle,
} from "@/components/bots-table";
import { CreateBotDialog } from "@/components/create-bot-dialog";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";

const ACCESS_LEVEL: Record<number, string> = {
    10: "Guest",
    20: "Reporter",
    30: "Developer",
    40: "Maintainer",
    50: "Owner",
};

export default function DashboardPage() {
    const { toast } = useToast();
    const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);
    const [selectedProjectPathName, setSelectedProjectPathName] = useState<
        string | null
    >(null);
    // Drives only the lightweight summary-card stats refetch. The bots table
    // updates affected rows in place, so it is intentionally NOT tied to this.
    const [statsRefreshTrigger, setStatsRefreshTrigger] = useState(0);
    const [botStats, setBotStats] = useState<{
        total: number;
        active: number;
        inactive: number;
    } | null>(null);
    const tableRef = useRef<BotsTableHandle>(null);

    // Fetch real bot stats for the summary cards
    useEffect(() => {
        let isCancelled = false;

        const loadStats = async () => {
            try {
                const response = await listBotsApiV1BotsGet();

                if (response.error || response.response.status !== 200) {
                    throw new Error("Failed to fetch bot stats");
                }

                const items = response.data.items ?? [];
                const active = items.filter((bot) => bot.is_active).length;

                if (!isCancelled) {
                    setBotStats({
                        total: response.data.total ?? items.length,
                        active,
                        inactive: items.length - active,
                    });
                }
            } catch (error) {
                console.error("Error fetching bot stats:", error);
                if (!isCancelled) {
                    setBotStats(null);
                }
            }
        };

        loadStats();

        return () => {
            isCancelled = true;
        };
    }, [statsRefreshTrigger]);

    const handleOpenCreateDialog = (projectPathName: string) => {
        setSelectedProjectPathName(projectPathName);
        setIsCreateDialogOpen(true);
    };

    const handleCreateBot = async (botName: string, projectPath: string) => {
        const response = await createBotApiV1BotsPost({
            body: {
                name: botName,
                gitlab_project_path: projectPath,
            },
        });

        if (response.error) {
            throw new Error("Failed to create bot");
        }

        if (response.response.status !== 201) {
            throw new Error(
                `Failed to create bot: ${response.response.statusText}`,
            );
        }

        // Patch just the affected project row in place instead of reloading.
        tableRef.current?.applyBotCreated(projectPath, {
            botId: response.data.bot.id,
            botName,
            avatar: response.data.bot.avatar_url ?? undefined,
        });
        setStatsRefreshTrigger((prev) => prev + 1);

        toast({
            variant: response.data.warning ? "warning" : "success",
            title: `Bot "${botName}" created`,
            description: response.data.warning ?? undefined,
        });
    };

    // Fetch bots from API
    const fetchBots = useCallback(
        async (
            page: number,
            perPage: number,
            search?: string,
        ): Promise<Bot[]> => {
            try {
                const searchTerm = search?.trim();
                const query: {
                    page: number;
                    per_page: number;
                    search?: string;
                } = {
                    page,
                    per_page: perPage,
                };

                if (searchTerm) {
                    query.search = searchTerm;
                }

                const response = await listGitlabProjectsApiV1GitlabProjectsGet(
                    {
                        query,
                    },
                );

                if (response.error) {
                    throw new Error("Wrong input type.");
                }

                if (response.response.status !== 200) {
                    throw new Error(
                        `Failed to fetch bots: ${response.response.statusText}`,
                    );
                }

                const rawProjects = Array.isArray(response.data)
                    ? response.data
                    : [];

                return rawProjects.map((project: any) => {
                    return {
                        gitlabProjectId: project.id,
                        gitlabProject: project.name_with_namespace,
                        gitlabProjectPathName: project.path_with_namespace,
                        projectUrl: project.web_url,
                        accessLevel: ACCESS_LEVEL[project.access_level],
                        botId: project.bot_id ?? undefined,
                        botName: project.bot_name ?? undefined,
                        avatar: project.avatar_url ?? undefined,
                        hasBot: Boolean(project.bot_id),
                    } as Bot;
                });
            } catch (error) {
                console.error("Error fetching bots:", error);
                throw error instanceof Error
                    ? error
                    : new Error("Unknown error while fetching bots");
            }
        },
        [],
    );

    // Fetch bot status from API
    const fetchBotStatus = async (botId: number): Promise<BotStatus> => {
        try {
            const response = await getBotStatusApiV1BotsBotIdStatusGet({
                path: { bot_id: botId },
            });

            if (response.error) {
                // Check if it's a 404 (bot not found - likely deleted)
                if (response.response.status === 404) {
                    throw new Error(
                        `Bot ${botId} not found (may have been deleted)`,
                    );
                }
                throw new Error(
                    `Failed to fetch bot status: ${response.error}`,
                );
            }

            if (response.response.status !== 200) {
                throw new Error(
                    `Failed to fetch bot status: ${response.response.statusText}`,
                );
            }
            return {
                status: response.data.status,
                errorMessage: response.data.error_message ?? undefined,
            };
        } catch (error) {
            console.error(`Error fetching status for bot ${botId}:`, error);
            throw error instanceof Error
                ? error
                : new Error("Unknown error while fetching bot status");
        }
    };

    // Toggle a bot active/inactive. Returns false on failure so the table can
    // skip its in-place status refresh.
    const handleStopBot = async (
        botId: number,
        botName: string,
    ): Promise<boolean> => {
        try {
            console.log(`Toggling bot status for: ${botName} (ID: ${botId})`);

            const response =
                await toggleBotActiveApiV1BotsBotIdToggleActivePatch({
                    path: { bot_id: botId },
                });

            if (response.error) {
                throw new Error("Wrong input type.");
            }

            if (response.response.status !== 200) {
                throw new Error(
                    `Failed to toggle bot status: ${response.response.statusText}`,
                );
            }

            const isActive = response.data.is_active;
            toast({
                variant: "success",
                title: `Bot "${botName}" ${isActive ? "activated" : "deactivated"}`,
                description: `The bot is now ${isActive ? "active" : "inactive"}.`,
            });

            // Only the summary cards need a refresh; the table updates the row.
            setStatsRefreshTrigger((prev) => prev + 1);
            return true;
        } catch (error) {
            console.error(`Error toggling bot status for ${botName}:`, error);
            toast({
                variant: "error",
                title: "Failed to toggle bot status",
                description:
                    error instanceof Error ? error.message : "Unknown error",
            });
            return false;
        }
    };

    // Issue a fresh access token for a bot. Returns false on failure.
    const handleCreateNewToken = async (
        botId: number,
        botName: string,
    ): Promise<boolean> => {
        try {
            console.log(`Creating new token for: ${botName} (ID: ${botId})`);

            const response =
                await createNewBotAccessTokenApiV1BotsBotIdNewAccessTokenPatch({
                    path: { bot_id: botId },
                });

            if (response.error) {
                throw new Error("Wrong input type.");
            }

            if (response.response.status !== 200) {
                throw new Error(
                    `Failed to create new token: ${response.response.statusText}`,
                );
            }

            toast({
                variant: response.data.warning ? "warning" : "success",
                title: `New token created for "${botName}"`,
                description: response.data.warning
                    ? `The old token has been invalidated.\nWarning: ${response.data.warning}`
                    : "The old token has been invalidated.",
            });

            setStatsRefreshTrigger((prev) => prev + 1);
            return true;
        } catch (error) {
            console.error(`Error creating new token for ${botName}:`, error);
            toast({
                variant: "error",
                title: "Failed to create new token",
                description:
                    error instanceof Error ? error.message : "Unknown error",
            });
            return false;
        }
    };

    // Delete a bot. Returns false on failure so the table keeps the row.
    const handleRemoveBot = async (
        botId: number,
        botName: string,
    ): Promise<boolean> => {
        try {
            console.log(`Removing bot: ${botName} (ID: ${botId})`);
            const response = await deleteBotApiV1BotsBotIdDelete({
                path: { bot_id: botId },
            });

            if (response.error) {
                throw new Error(`Wrong input type.`);
            }

            if (response.response.status !== 200) {
                throw new Error(
                    `Failed to remove bot: ${response.response.statusText}`,
                );
            }

            toast({
                variant: response.data.warning ? "warning" : "success",
                title: `Bot "${botName}" removed`,
                description: response.data.warning
                    ? `Warning: ${response.data.warning}`
                    : undefined,
            });

            setStatsRefreshTrigger((prev) => prev + 1);
            return true;
        } catch (error) {
            console.error(`Error removing bot ${botName}:`, error);
            toast({
                variant: "error",
                title: "Failed to remove bot",
                description:
                    error instanceof Error ? error.message : "Unknown error",
            });
            return false;
        }
    };

    return (
        <div className="space-y-6">
            <div>
                <h2 className="text-3xl font-bold tracking-tight">Dashboard</h2>
                <p className="text-muted-foreground">
                    Welcome to your GitLab Agent dashboard
                </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <Card>
                    <CardHeader>
                        <CardTitle>Total Bots</CardTitle>
                        <CardDescription>AI bots configured</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <p className="text-3xl font-bold">
                            {botStats ? botStats.total : "—"}
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle>Active</CardTitle>
                        <CardDescription>Currently running</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <p className="text-3xl font-bold text-green-600">
                            {botStats ? botStats.active : "—"}
                        </p>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle>Inactive</CardTitle>
                        <CardDescription>Stopped bots</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <p className="text-3xl font-bold text-muted-foreground">
                            {botStats ? botStats.inactive : "—"}
                        </p>
                    </CardContent>
                </Card>
            </div>

            {/* Bots Table */}
            <Card>
                <CardHeader>
                    <CardTitle>Bots</CardTitle>
                    <CardDescription>
                        Manage your GitLab bots and their configurations
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <BotsTable
                        ref={tableRef}
                        fetchBots={fetchBots}
                        fetchBotStatus={fetchBotStatus}
                        onCreateBot={handleOpenCreateDialog}
                        onStopBot={handleStopBot}
                        onCreateNewToken={handleCreateNewToken}
                        onRemoveBot={handleRemoveBot}
                    />
                </CardContent>
            </Card>

            {/* Create Bot Dialog */}
            <CreateBotDialog
                isOpen={isCreateDialogOpen}
                onOpenChange={setIsCreateDialogOpen}
                projectPathName={selectedProjectPathName}
                onCreateBot={handleCreateBot}
            />
        </div>
    );
}
