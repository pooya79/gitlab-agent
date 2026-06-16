"use client";

import {
    AlertCircle,
    BarChart3,
    CheckCircle2,
    KeyRound,
    Loader2,
    MoreVertical,
    Pause,
    Play,
    Search,
    Settings,
    StopCircle,
    Trash2,
    XCircle,
} from "lucide-react";
import Link from "next/link";
import {
    forwardRef,
    useCallback,
    useEffect,
    useImperativeHandle,
    useRef,
    useState,
} from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";

type StatusLiterals = "ACTIVE" | "STOPPED" | "ERROR";

const PAGE_SIZE = 20;

// Types
export interface Bot {
    gitlabProjectId: number;
    gitlabProject: string;
    gitlabProjectPathName: string;
    projectUrl: string;
    accessLevel: "Owner" | "Maintainer" | "Developer" | "Reporter" | "Guest";
    botId?: number; // Optional - null if no bot configured
    botName?: string; // Optional - null if no bot configured
    avatar?: string; // Optional - null if no bot configured
    status?: StatusLiterals; // Optional - null if no bot configured
    errorMessage?: string;
    hasBot: boolean; // Indicates if project has a bot configured
}

export interface BotStatus {
    status: StatusLiterals;
    errorMessage?: string;
}

interface BotsTableProps {
    fetchBots: (
        page: number,
        perPage: number,
        search?: string,
    ) => Promise<Bot[]>;
    fetchBotStatus?: (botId: number) => Promise<BotStatus>;
    onCreateBot?: (projectPathName: string) => void;
    // Action handlers return `false` to signal failure so the table can skip
    // the optimistic local update; any other value is treated as success.
    onStopBot?: (botId: number, botName: string) => Promise<boolean>;
    onCreateNewToken?: (botId: number, botName: string) => Promise<boolean>;
    onRemoveBot?: (botId: number, botName: string) => Promise<boolean>;
}

// Imperative handle so the parent can patch a single row (e.g. after creating
// a bot) without forcing the whole table to refetch and reset.
export interface BotsTableHandle {
    applyBotCreated: (
        projectPathName: string,
        bot: { botId: number; botName: string; avatar?: string },
    ) => void;
}

export const BotsTable = forwardRef<BotsTableHandle, BotsTableProps>(
    function BotsTable(
        {
            fetchBots,
            fetchBotStatus,
            onCreateBot,
            onStopBot,
            onCreateNewToken,
            onRemoveBot,
        }: BotsTableProps,
        ref,
    ) {
        const [page, setPage] = useState(1);
        const [bots, setBots] = useState<Bot[]>([]);
        const [hasMore, setHasMore] = useState(true);
        const [loadingState, setLoadingState] = useState<
            "idle" | "initial" | "more"
        >("initial");
        const [error, setError] = useState<string | null>(null);
        const [searchInput, setSearchInput] = useState("");
        const [searchQuery, setSearchQuery] = useState("");
        const [loadedPages, setLoadedPages] = useState(0);
        const [requestVersion, setRequestVersion] = useState(0);
        const [failedPage, setFailedPage] = useState<number | null>(null);
        const [botStatuses, setBotStatuses] = useState<Map<number, BotStatus>>(
            new Map(),
        );
        const [loadingStatuses, setLoadingStatuses] = useState<Set<number>>(
            new Set(),
        );
        // Pending in-app confirmation (replaces the native window.confirm()).
        const [pendingConfirm, setPendingConfirm] = useState<{
            title: string;
            description: string;
            confirmLabel: string;
            destructive: boolean;
            run: () => Promise<void>;
        } | null>(null);
        const [isConfirming, setIsConfirming] = useState(false);
        const isLoading = loadingState !== "idle";
        const isInitialLoading = loadingState === "initial";
        const isFetchingMore = loadingState === "more";
        const observerRef = useRef<IntersectionObserver | null>(null);
        // Bot IDs whose status has already been requested, so the bulk-status
        // effect only fetches newly-appeared bots instead of reloading every row.
        const requestedStatusIdsRef = useRef<Set<number>>(new Set());

        // Fetch (or refetch) the status of a single bot in place.
        const refreshSingleStatus = useCallback(
            async (botId: number) => {
                if (!fetchBotStatus) return;
                requestedStatusIdsRef.current.add(botId);
                setLoadingStatuses((prev) => new Set(prev).add(botId));
                try {
                    const status = await fetchBotStatus(botId);
                    setBotStatuses((prev) => new Map(prev).set(botId, status));
                } catch (err) {
                    const message = err instanceof Error ? err.message : "";
                    const isNotFoundError =
                        message.includes("not found") ||
                        message.includes("deleted");
                    if (!isNotFoundError) {
                        setBotStatuses((prev) =>
                            new Map(prev).set(botId, {
                                status: "ERROR",
                                errorMessage: "Failed to fetch bot status",
                            }),
                        );
                    }
                    console.error(
                        `Failed to fetch status for bot ID: ${botId}:`,
                        err,
                    );
                } finally {
                    setLoadingStatuses((prev) => {
                        const newSet = new Set(prev);
                        newSet.delete(botId);
                        return newSet;
                    });
                }
            },
            [fetchBotStatus],
        );

        const handleLoadMore = useCallback(() => {
            if (!hasMore || isLoading) {
                return;
            }

            const nextPage = failedPage ?? loadedPages + 1;

            if (nextPage <= 0) {
                return;
            }

            if (page === nextPage) {
                if (failedPage !== null) {
                    setRequestVersion((prev) => prev + 1);
                }
                return;
            }

            setPage(nextPage);
        }, [failedPage, hasMore, isLoading, loadedPages, page]);

        const loadMoreRef = useCallback(
            (node: HTMLDivElement | null) => {
                if (observerRef.current) {
                    observerRef.current.disconnect();
                }

                if (!node) {
                    return;
                }

                observerRef.current = new IntersectionObserver(
                    (entries) => {
                        if (entries[0]?.isIntersecting) {
                            handleLoadMore();
                        }
                    },
                    {
                        root: null,
                        rootMargin: "200px",
                        threshold: 0,
                    },
                );

                observerRef.current.observe(node);
            },
            [handleLoadMore],
        );

        useEffect(() => {
            return () => {
                observerRef.current?.disconnect();
            };
        }, []);

        useEffect(() => {
            const handler = setTimeout(() => {
                setSearchQuery(searchInput.trim());
            }, 400);

            return () => {
                clearTimeout(handler);
            };
        }, [searchInput]);

        useEffect(() => {
            setBots([]);
            setHasMore(true);
            setPage(1);
            setLoadedPages(0);
            setFailedPage(null);
        }, [searchQuery, fetchBots]);

        useEffect(() => {
            let isCancelled = false;

            const loadBots = async () => {
                setError(null);
                setFailedPage(null);
                setLoadingState(page === 1 ? "initial" : "more");

                try {
                    const result = await fetchBots(
                        page,
                        PAGE_SIZE,
                        searchQuery,
                    );
                    if (isCancelled) {
                        return;
                    }

                    const nextBots = Array.isArray(result) ? result : [];

                    setBots((prev) =>
                        page === 1 ? nextBots : [...prev, ...nextBots],
                    );
                    setHasMore(nextBots.length === PAGE_SIZE);
                    setLoadedPages(page);
                    setFailedPage(null);
                } catch (err) {
                    if (!isCancelled) {
                        const message =
                            err instanceof Error
                                ? err.message
                                : "Failed to fetch bots";
                        setError(message);
                        setFailedPage(page);
                        console.error("Error fetching bots:", err);
                    }
                } finally {
                    if (!isCancelled) {
                        setLoadingState("idle");
                    }
                }
            };

            loadBots();

            return () => {
                isCancelled = true;
            };
        }, [page, fetchBots, searchQuery, requestVersion]);

        // Fetch statuses for bots that have a bot configured. Only newly-appeared
        // bots are fetched; existing rows keep their status so a single-row action
        // never makes the whole table flash back to "Loading…".
        useEffect(() => {
            if (!fetchBotStatus || bots.length === 0) return;

            const botsWithBots = bots.filter((bot) => bot.hasBot);
            const currentBotIds = new Set(
                botsWithBots.map((bot) => bot.botId!),
            );

            // Forget bots that are no longer in the list (also drops their status)
            // so they refetch if they reappear later.
            for (const botId of requestedStatusIdsRef.current) {
                if (!currentBotIds.has(botId)) {
                    requestedStatusIdsRef.current.delete(botId);
                }
            }
            setBotStatuses((prev) => {
                let changed = false;
                const newMap = new Map(prev);
                for (const botId of newMap.keys()) {
                    if (!currentBotIds.has(botId)) {
                        newMap.delete(botId);
                        changed = true;
                    }
                }
                return changed ? newMap : prev;
            });

            // Fetch only bots we haven't requested yet.
            for (const bot of botsWithBots) {
                if (!requestedStatusIdsRef.current.has(bot.botId!)) {
                    refreshSingleStatus(bot.botId!);
                }
            }
        }, [bots, fetchBotStatus, refreshSingleStatus]);

        // Get the current status for a bot (prioritize fetched status over initial data)
        const getBotStatus = (
            bot: Bot,
        ): {
            status: Bot["status"];
            errorMessage?: string;
            isLoading: boolean;
        } => {
            if (bot.hasBot && bot.botId) {
                // Check if status is currently being loaded
                if (fetchBotStatus && loadingStatuses.has(bot.botId)) {
                    return {
                        status: undefined,
                        isLoading: true,
                    };
                }

                // Check if we have a fetched status
                if (botStatuses.has(bot.botId)) {
                    const fetchedStatus = botStatuses.get(bot.botId)!;
                    return {
                        status: fetchedStatus.status,
                        errorMessage: fetchedStatus.errorMessage,
                        isLoading: false,
                    };
                }
            }

            // Return initial status from bot data
            return {
                status: bot.status,
                errorMessage: bot.errorMessage,
                isLoading: false,
            };
        };

        // Turn a project row back into an unconfigured ("No bot") row in place.
        const clearBotFromRow = useCallback((botId: number) => {
            setBots((prev) =>
                prev.map((bot) =>
                    bot.botId === botId
                        ? {
                              ...bot,
                              hasBot: false,
                              botId: undefined,
                              botName: undefined,
                              avatar: undefined,
                              status: undefined,
                              errorMessage: undefined,
                          }
                        : bot,
                ),
            );
            requestedStatusIdsRef.current.delete(botId);
            setBotStatuses((prev) => {
                if (!prev.has(botId)) return prev;
                const newMap = new Map(prev);
                newMap.delete(botId);
                return newMap;
            });
        }, []);

        // Destructive/irreversible actions go through an in-app confirmation
        // dialog instead of the native window.confirm().
        const requestRemoveBot = (botId: number, botName: string) => {
            setPendingConfirm({
                title: "Remove bot",
                description: `Are you sure you want to remove "${botName}"? This revokes its GitLab access token and webhook.`,
                confirmLabel: "Remove",
                destructive: true,
                run: async () => {
                    const result = await onRemoveBot?.(botId, botName);
                    if (result === false) return;
                    clearBotFromRow(botId);
                },
            });
        };

        const handleStopBot = async (botId: number, botName: string) => {
            const result = await onStopBot?.(botId, botName);
            if (result === false) return;
            await refreshSingleStatus(botId);
        };

        const requestCreateNewToken = (botId: number, botName: string) => {
            setPendingConfirm({
                title: "Create new token",
                description: `Are you sure you want to create a new token for "${botName}"? This will invalidate the old token.`,
                confirmLabel: "Create token",
                destructive: false,
                run: async () => {
                    const result = await onCreateNewToken?.(botId, botName);
                    if (result === false) return;
                    await refreshSingleStatus(botId);
                },
            });
        };

        const handleConfirm = async () => {
            if (!pendingConfirm) return;
            setIsConfirming(true);
            try {
                await pendingConfirm.run();
            } finally {
                setIsConfirming(false);
                setPendingConfirm(null);
            }
        };

        useImperativeHandle(
            ref,
            () => ({
                applyBotCreated: (projectPathName, bot) => {
                    setBots((prev) =>
                        prev.map((row) =>
                            row.gitlabProjectPathName === projectPathName
                                ? {
                                      ...row,
                                      hasBot: true,
                                      botId: bot.botId,
                                      botName: bot.botName,
                                      avatar: bot.avatar,
                                  }
                                : row,
                        ),
                    );
                    // Pull the freshly-created bot's real status in place; the
                    // bulk effect would also do this, but this is more direct.
                    refreshSingleStatus(bot.botId);
                },
            }),
            [refreshSingleStatus],
        );

        const handleRetry = () => {
            setRequestVersion((prev) => prev + 1);
        };

        const getStatusBadge = (
            status: Bot["status"],
            errorMessage?: string,
        ) => {
            switch (status) {
                case "ACTIVE":
                    return (
                        <Badge
                            variant="default"
                            className="bg-green-600 hover:bg-green-700"
                        >
                            <CheckCircle2 className="h-3 w-3" />
                            Active
                        </Badge>
                    );
                case "STOPPED":
                    return (
                        <Badge variant="secondary">
                            <Pause className="h-3 w-3" />
                            Stopped
                        </Badge>
                    );
                case "ERROR":
                    return (
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Badge
                                        variant="destructive"
                                        className="cursor-help"
                                    >
                                        <XCircle className="h-3 w-3" />
                                        Error
                                    </Badge>
                                </TooltipTrigger>
                                <TooltipContent className="max-w-xs">
                                    <p>
                                        {errorMessage ||
                                            "An error occurred with this bot"}
                                    </p>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    );
                default:
                    return (
                        <Badge variant="outline">
                            <AlertCircle className="h-3 w-3" />
                            {status}
                        </Badge>
                    );
            }
        };

        const getAccessLevelBadge = (level: Bot["accessLevel"]) => {
            const variants = {
                Owner: "default",
                Maintainer: "secondary",
                Developer: "outline",
                Reporter: "outline",
                Guest: "outline",
            } as const;

            return <Badge variant={variants[level]}>{level}</Badge>;
        };

        const isSearching = searchQuery.length > 0;
        const emptyState = isSearching
            ? {
                  title: "No matching projects",
                  description: "Try a different search term.",
              }
            : {
                  title: "No bots configured",
                  description: "Add your first bot to get started",
              };
        const showErrorState = Boolean(error) && bots.length === 0;
        const showInlineError = Boolean(error) && bots.length > 0;

        return (
            <div className="space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="relative w-full sm:max-w-sm">
                        <Search
                            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                            aria-hidden="true"
                        />
                        <Input
                            type="search"
                            value={searchInput}
                            onChange={(event) =>
                                setSearchInput(event.target.value)
                            }
                            placeholder="Search projects"
                            className="pl-9"
                            aria-label="Search projects"
                        />
                    </div>
                    <p className="text-sm text-muted-foreground">
                        Showing {bots.length} project
                        {bots.length === 1 ? "" : "s"}
                    </p>
                </div>

                {/* Table */}
                <div className="rounded-md border overflow-hidden">
                    <div className="overflow-x-auto custom-scrollbar">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>Bot</TableHead>
                                    <TableHead>GitLab Project</TableHead>
                                    <TableHead>Access Level</TableHead>
                                    <TableHead>Status</TableHead>
                                    <TableHead>Links</TableHead>
                                    <TableHead className="text-right">
                                        Actions
                                    </TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {isInitialLoading ? (
                                    <TableRow key="loading">
                                        <TableCell
                                            colSpan={6}
                                            className="py-8 text-center"
                                        >
                                            <div className="flex items-center justify-center gap-2 text-muted-foreground">
                                                <Loader2 className="h-4 w-4 animate-spin" />
                                                <span>Loading bots...</span>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ) : showErrorState ? (
                                    <TableRow key="error">
                                        <TableCell
                                            colSpan={6}
                                            className="py-8 text-center"
                                        >
                                            <div className="text-destructive">
                                                <p className="text-lg font-medium">
                                                    Error loading bots
                                                </p>
                                                <p className="mt-1 text-sm">
                                                    {error}
                                                </p>
                                            </div>
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                className="mt-4"
                                                onClick={handleRetry}
                                            >
                                                Try again
                                            </Button>
                                        </TableCell>
                                    </TableRow>
                                ) : bots.length === 0 ? (
                                    <TableRow key="no-bots">
                                        <TableCell
                                            colSpan={6}
                                            className="py-8 text-center"
                                        >
                                            <div className="text-muted-foreground">
                                                <p className="text-lg font-medium">
                                                    {emptyState.title}
                                                </p>
                                                <p className="mt-1 text-sm">
                                                    {emptyState.description}
                                                </p>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ) : (
                                    <>
                                        {bots.map((bot) => (
                                            <TableRow key={bot.gitlabProjectId}>
                                                {/* Bot Name & Avatar */}
                                                <TableCell>
                                                    {bot.hasBot ? (
                                                        <div className="flex items-center gap-3">
                                                            <Avatar>
                                                                <AvatarImage
                                                                    src={
                                                                        bot.avatar
                                                                    }
                                                                    alt={
                                                                        bot.botName
                                                                    }
                                                                />
                                                                <AvatarFallback>
                                                                    {bot.botName
                                                                        ?.split(
                                                                            " ",
                                                                        )
                                                                        .map(
                                                                            (
                                                                                n,
                                                                            ) =>
                                                                                n[0],
                                                                        )
                                                                        .join(
                                                                            "",
                                                                        )
                                                                        .toUpperCase()}
                                                                </AvatarFallback>
                                                            </Avatar>
                                                            <div>
                                                                <p className="font-medium">
                                                                    {
                                                                        bot.botName
                                                                    }
                                                                </p>
                                                                <p className="text-xs text-muted-foreground">
                                                                    ID:{" "}
                                                                    {bot.botId}
                                                                </p>
                                                            </div>
                                                        </div>
                                                    ) : (
                                                        <div className="flex items-center gap-3">
                                                            <Avatar>
                                                                <AvatarFallback>
                                                                    <Settings className="h-4 w-4 text-muted-foreground" />
                                                                </AvatarFallback>
                                                            </Avatar>
                                                            <div>
                                                                <p className="text-sm text-muted-foreground italic">
                                                                    No bot
                                                                    configured
                                                                </p>
                                                            </div>
                                                        </div>
                                                    )}
                                                </TableCell>

                                                {/* GitLab Project */}
                                                <TableCell>
                                                    <a
                                                        href={bot.projectUrl}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="text-primary hover:underline"
                                                    >
                                                        {bot.gitlabProject}
                                                    </a>
                                                </TableCell>

                                                {/* Access Level */}
                                                <TableCell>
                                                    {getAccessLevelBadge(
                                                        bot.accessLevel,
                                                    )}
                                                </TableCell>

                                                {/* Status */}
                                                <TableCell>
                                                    {bot.hasBot ? (
                                                        (() => {
                                                            const {
                                                                status,
                                                                errorMessage,
                                                                isLoading,
                                                            } =
                                                                getBotStatus(
                                                                    bot,
                                                                );
                                                            if (isLoading) {
                                                                return (
                                                                    <Badge
                                                                        variant="outline"
                                                                        className="text-muted-foreground"
                                                                    >
                                                                        <AlertCircle className="h-3 w-3 animate-pulse" />
                                                                        Loading...
                                                                    </Badge>
                                                                );
                                                            }
                                                            return status ? (
                                                                getStatusBadge(
                                                                    status,
                                                                    errorMessage,
                                                                )
                                                            ) : (
                                                                <Badge
                                                                    variant="outline"
                                                                    className="text-muted-foreground"
                                                                >
                                                                    <AlertCircle className="h-3 w-3" />
                                                                    Unknown
                                                                </Badge>
                                                            );
                                                        })()
                                                    ) : (
                                                        <Badge
                                                            variant="outline"
                                                            className="text-muted-foreground"
                                                        >
                                                            <AlertCircle className="h-3 w-3" />
                                                            Not Active
                                                        </Badge>
                                                    )}
                                                </TableCell>

                                                {/* Links */}
                                                <TableCell>
                                                    {bot.hasBot ? (
                                                        <div className="flex gap-1">
                                                            <TooltipProvider>
                                                                <Tooltip>
                                                                    <TooltipTrigger
                                                                        asChild
                                                                    >
                                                                        <Link
                                                                            href={`/dashboard/bots/${bot.botId}/stats`}
                                                                        >
                                                                            <Button
                                                                                variant="outline"
                                                                                size="sm"
                                                                            >
                                                                                <BarChart3 className="h-4 w-4" />
                                                                            </Button>
                                                                        </Link>
                                                                    </TooltipTrigger>
                                                                    <TooltipContent>
                                                                        <p>
                                                                            View
                                                                            Stats
                                                                        </p>
                                                                    </TooltipContent>
                                                                </Tooltip>
                                                            </TooltipProvider>

                                                            <TooltipProvider>
                                                                <Tooltip>
                                                                    <TooltipTrigger
                                                                        asChild
                                                                    >
                                                                        <Link
                                                                            href={`/dashboard/bots/${bot.botId}/configs`}
                                                                        >
                                                                            <Button
                                                                                variant="outline"
                                                                                size="sm"
                                                                            >
                                                                                <Settings className="h-4 w-4" />
                                                                            </Button>
                                                                        </Link>
                                                                    </TooltipTrigger>
                                                                    <TooltipContent>
                                                                        <p>
                                                                            Configure
                                                                        </p>
                                                                    </TooltipContent>
                                                                </Tooltip>
                                                            </TooltipProvider>
                                                        </div>
                                                    ) : (
                                                        <Button
                                                            variant="default"
                                                            size="sm"
                                                            onClick={() =>
                                                                onCreateBot?.(
                                                                    bot.gitlabProjectPathName,
                                                                )
                                                            }
                                                        >
                                                            <Play className="mr-2 h-4 w-4" />
                                                            Create Bot
                                                        </Button>
                                                    )}
                                                </TableCell>

                                                {/* Actions */}
                                                <TableCell className="text-right">
                                                    {bot.hasBot ? (
                                                        (() => {
                                                            const { status } =
                                                                getBotStatus(
                                                                    bot,
                                                                );
                                                            return (
                                                                <DropdownMenu>
                                                                    <DropdownMenuTrigger
                                                                        asChild
                                                                    >
                                                                        <Button
                                                                            variant="outline"
                                                                            size="sm"
                                                                        >
                                                                            <MoreVertical className="h-4 w-4" />
                                                                        </Button>
                                                                    </DropdownMenuTrigger>
                                                                    <DropdownMenuContent align="end">
                                                                        <DropdownMenuItem
                                                                            onClick={() =>
                                                                                handleStopBot(
                                                                                    bot.botId!,
                                                                                    bot.botName!,
                                                                                )
                                                                            }
                                                                            disabled={
                                                                                status ===
                                                                                "ERROR"
                                                                            }
                                                                        >
                                                                            {status ===
                                                                            "STOPPED" ? (
                                                                                <>
                                                                                    <Play className="mr-2 h-4 w-4" />
                                                                                    Start
                                                                                    Bot
                                                                                </>
                                                                            ) : (
                                                                                <>
                                                                                    <StopCircle className="mr-2 h-4 w-4" />
                                                                                    Stop
                                                                                    Bot
                                                                                </>
                                                                            )}
                                                                        </DropdownMenuItem>
                                                                        <DropdownMenuItem
                                                                            onClick={() =>
                                                                                requestCreateNewToken(
                                                                                    bot.botId!,
                                                                                    bot.botName!,
                                                                                )
                                                                            }
                                                                        >
                                                                            <KeyRound className="mr-2 h-4 w-4" />
                                                                            Create
                                                                            New
                                                                            Token
                                                                        </DropdownMenuItem>
                                                                        <DropdownMenuSeparator />
                                                                        <DropdownMenuItem
                                                                            onClick={() =>
                                                                                requestRemoveBot(
                                                                                    bot.botId!,
                                                                                    bot.botName!,
                                                                                )
                                                                            }
                                                                            className="text-destructive focus:text-destructive"
                                                                        >
                                                                            <Trash2 className="mr-2 h-4 w-4" />
                                                                            Remove
                                                                            Bot
                                                                        </DropdownMenuItem>
                                                                    </DropdownMenuContent>
                                                                </DropdownMenu>
                                                            );
                                                        })()
                                                    ) : (
                                                        <span className="text-xs text-muted-foreground">
                                                            —
                                                        </span>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                        {isFetchingMore && (
                                            <TableRow key="loading-more">
                                                <TableCell
                                                    colSpan={6}
                                                    className="py-6 text-center"
                                                >
                                                    <div className="flex items-center justify-center gap-2 text-muted-foreground">
                                                        <Loader2 className="h-4 w-4 animate-spin" />
                                                        <span>
                                                            Loading more bots...
                                                        </span>
                                                    </div>
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </>
                                )}
                            </TableBody>
                        </Table>
                    </div>
                </div>

                {showInlineError && (
                    <div className="flex flex-col items-center justify-center gap-2 text-sm text-destructive sm:flex-row">
                        <span>Failed to load more bots: {error}</span>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={handleRetry}
                        >
                            Try again
                        </Button>
                    </div>
                )}

                <div
                    ref={loadMoreRef}
                    aria-hidden="true"
                    className="h-px w-full"
                />

                {/* Custom Scrollbar Styles */}
                <style jsx global>{`
                .custom-scrollbar::-webkit-scrollbar {
                    height: 8px;
                }
                .custom-scrollbar::-webkit-scrollbar-track {
                    background: hsl(var(--muted));
                    border-radius: 4px;
                }
                .custom-scrollbar::-webkit-scrollbar-thumb {
                    background: hsl(var(--muted-foreground) / 0.3);
                    border-radius: 4px;
                }
                .custom-scrollbar::-webkit-scrollbar-thumb:hover {
                    background: hsl(var(--muted-foreground) / 0.5);
                }
                /* Firefox */
                .custom-scrollbar {
                    scrollbar-width: thin;
                    scrollbar-color: hsl(var(--muted-foreground) / 0.3)
                        hsl(var(--muted));
                }
            `}</style>

                <ConfirmDialog
                    open={pendingConfirm !== null}
                    title={pendingConfirm?.title ?? ""}
                    description={pendingConfirm?.description}
                    confirmLabel={pendingConfirm?.confirmLabel}
                    destructive={pendingConfirm?.destructive}
                    loading={isConfirming}
                    onConfirm={handleConfirm}
                    onCancel={() => setPendingConfirm(null)}
                />
            </div>
        );
    },
);
