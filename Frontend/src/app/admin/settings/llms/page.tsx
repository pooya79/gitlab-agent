"use client";

import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
    addUpdateLlmConfigApiV1AdminSettingsLlmsPost,
    deleteLlmConfigApiV1AdminSettingsLlmsModelNameDelete,
    listLlmConfigsApiV1AdminSettingsLlmsGet,
} from "@/client/sdk.gen";
import type { LlmModelInfo } from "@/client/types.gen";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";

type FormState = {
    model_name: string;
    context_window: string;
    max_output_tokens: string;
    temperature: string;
    top_p: string;
    input_token_cost: string;
    output_token_cost: string;
    additional_kwargs_schema: string;
};

const EMPTY_FORM: FormState = {
    model_name: "",
    context_window: "16384",
    max_output_tokens: "16384",
    temperature: "0.2",
    top_p: "0.95",
    input_token_cost: "0",
    output_token_cost: "0",
    additional_kwargs_schema: "{}",
};

function toForm(info: LlmModelInfo): FormState {
    return {
        model_name: info.model_name,
        context_window: String(info.context_window),
        max_output_tokens: String(info.max_output_tokens),
        temperature: String(info.temperature ?? 0.2),
        top_p: String(info.top_p ?? 0.95),
        input_token_cost: String(info.input_token_cost ?? 0),
        output_token_cost: String(info.output_token_cost ?? 0),
        additional_kwargs_schema: JSON.stringify(
            info.additional_kwargs_schema ?? {},
            null,
            2,
        ),
    };
}

export default function LlmSettingsPage() {
    const [models, setModels] = useState<LlmModelInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);

    const [dialogOpen, setDialogOpen] = useState(false);
    // null model_name = creating a new model; otherwise editing that key.
    const [editingKey, setEditingKey] = useState<string | null>(null);
    const [form, setForm] = useState<FormState>(EMPTY_FORM);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    const [deletingKey, setDeletingKey] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setLoadError(null);
        try {
            const response = await listLlmConfigsApiV1AdminSettingsLlmsGet();
            if (response.error || !response.data) {
                setLoadError("Failed to load LLM models.");
                return;
            }
            setModels(Object.values(response.data));
        } catch {
            setLoadError("Failed to load LLM models.");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const openCreate = () => {
        setEditingKey(null);
        setForm(EMPTY_FORM);
        setFormError(null);
        setDialogOpen(true);
    };

    const openEdit = (info: LlmModelInfo) => {
        setEditingKey(info.model_name);
        setForm(toForm(info));
        setFormError(null);
        setDialogOpen(true);
    };

    const setField = (key: keyof FormState, value: string) =>
        setForm((prev) => ({ ...prev, [key]: value }));

    const handleSave = async () => {
        setFormError(null);

        const name = form.model_name.trim();
        if (!name) {
            setFormError("Model name is required.");
            return;
        }

        let additionalKwargs: Record<string, unknown>;
        try {
            const parsed = JSON.parse(form.additional_kwargs_schema || "{}");
            if (
                typeof parsed !== "object" ||
                parsed === null ||
                Array.isArray(parsed)
            ) {
                throw new Error("not an object");
            }
            additionalKwargs = parsed;
        } catch {
            setFormError("Additional params must be a valid JSON object.");
            return;
        }

        const numbers = {
            context_window: Number(form.context_window),
            max_output_tokens: Number(form.max_output_tokens),
            temperature: Number(form.temperature),
            top_p: Number(form.top_p),
            input_token_cost: Number(form.input_token_cost),
            output_token_cost: Number(form.output_token_cost),
        };
        if (Object.values(numbers).some((n) => Number.isNaN(n))) {
            setFormError("All numeric fields must be valid numbers.");
            return;
        }

        setSaving(true);
        try {
            const response = await addUpdateLlmConfigApiV1AdminSettingsLlmsPost(
                {
                    body: {
                        model_name: name,
                        ...numbers,
                        additional_kwargs_schema: additionalKwargs,
                    },
                },
            );
            if (response.error || !response.data) {
                setFormError("Failed to save model.");
                return;
            }
            setDialogOpen(false);
            await load();
        } catch {
            setFormError("Failed to save model.");
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (modelName: string) => {
        if (
            !window.confirm(
                `Delete LLM model "${modelName}"? Bots already using it keep their settings.`,
            )
        ) {
            return;
        }
        setDeletingKey(modelName);
        try {
            const response =
                await deleteLlmConfigApiV1AdminSettingsLlmsModelNameDelete({
                    path: { model_name: modelName },
                });
            if (response.error) {
                setLoadError(`Failed to delete "${modelName}".`);
                return;
            }
            await load();
        } catch {
            setLoadError(`Failed to delete "${modelName}".`);
        } finally {
            setDeletingKey(null);
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
        <div className="space-y-6">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-2xl font-bold">LLM Models</h2>
                    <p className="text-muted-foreground">
                        The catalog of models bots can be configured to use.
                        Costs are per 1M tokens.
                    </p>
                </div>
                <Button onClick={openCreate}>
                    <Plus className="mr-2 h-4 w-4" />
                    Add model
                </Button>
            </div>

            {loadError && (
                <Alert variant="destructive">
                    <AlertDescription>{loadError}</AlertDescription>
                </Alert>
            )}

            <div className="rounded-md border">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Model</TableHead>
                            <TableHead className="text-right">
                                Max tokens
                            </TableHead>
                            <TableHead className="text-right">Temp</TableHead>
                            <TableHead className="text-right">Top P</TableHead>
                            <TableHead className="text-right">
                                In $/1M
                            </TableHead>
                            <TableHead className="text-right">
                                Out $/1M
                            </TableHead>
                            <TableHead className="w-24" />
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {models.length === 0 ? (
                            <TableRow>
                                <TableCell
                                    colSpan={7}
                                    className="text-center text-muted-foreground"
                                >
                                    No models configured yet.
                                </TableCell>
                            </TableRow>
                        ) : (
                            models.map((m) => (
                                <TableRow key={m.model_name}>
                                    <TableCell className="font-mono">
                                        {m.model_name}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {m.max_output_tokens}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {m.temperature ?? 0.2}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {m.top_p ?? 0.95}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {m.input_token_cost ?? 0}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        {m.output_token_cost ?? 0}
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex justify-end gap-1">
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => openEdit(m)}
                                            >
                                                <Pencil className="h-4 w-4" />
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                disabled={
                                                    deletingKey === m.model_name
                                                }
                                                onClick={() =>
                                                    handleDelete(m.model_name)
                                                }
                                            >
                                                {deletingKey ===
                                                m.model_name ? (
                                                    <Loader2 className="h-4 w-4 animate-spin" />
                                                ) : (
                                                    <Trash2 className="h-4 w-4" />
                                                )}
                                            </Button>
                                        </div>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>

            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>
                            {editingKey ? "Edit model" : "Add model"}
                        </DialogTitle>
                        <DialogDescription>
                            Provider-prefixed model name as used by OpenRouter,
                            e.g. <code>openai/gpt-4o-mini</code>.
                        </DialogDescription>
                    </DialogHeader>

                    <div className="space-y-4">
                        <div className="space-y-2">
                            <Label htmlFor="model_name">Model name</Label>
                            <Input
                                id="model_name"
                                placeholder="openai/gpt-4o-mini"
                                value={form.model_name}
                                disabled={editingKey !== null}
                                onChange={(e) =>
                                    setField("model_name", e.target.value)
                                }
                            />
                            {editingKey !== null && (
                                <p className="text-xs text-muted-foreground">
                                    The model name is the identifier and
                                    can&apos;t be changed. Delete and re-add to
                                    rename.
                                </p>
                            )}
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label htmlFor="context_window">
                                    Context window
                                </Label>
                                <Input
                                    id="context_window"
                                    type="number"
                                    value={form.context_window}
                                    onChange={(e) =>
                                        setField(
                                            "context_window",
                                            e.target.value,
                                        )
                                    }
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="max_output_tokens">
                                    Max tokens
                                </Label>
                                <Input
                                    id="max_output_tokens"
                                    type="number"
                                    value={form.max_output_tokens}
                                    onChange={(e) =>
                                        setField(
                                            "max_output_tokens",
                                            e.target.value,
                                        )
                                    }
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="temperature">Temperature</Label>
                                <Input
                                    id="temperature"
                                    type="number"
                                    step="0.05"
                                    value={form.temperature}
                                    onChange={(e) =>
                                        setField("temperature", e.target.value)
                                    }
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="top_p">Top P</Label>
                                <Input
                                    id="top_p"
                                    type="number"
                                    step="0.05"
                                    value={form.top_p}
                                    onChange={(e) =>
                                        setField("top_p", e.target.value)
                                    }
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="input_token_cost">
                                    Input cost /1M
                                </Label>
                                <Input
                                    id="input_token_cost"
                                    type="number"
                                    step="0.01"
                                    value={form.input_token_cost}
                                    onChange={(e) =>
                                        setField(
                                            "input_token_cost",
                                            e.target.value,
                                        )
                                    }
                                />
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="output_token_cost">
                                    Output cost /1M
                                </Label>
                                <Input
                                    id="output_token_cost"
                                    type="number"
                                    step="0.01"
                                    value={form.output_token_cost}
                                    onChange={(e) =>
                                        setField(
                                            "output_token_cost",
                                            e.target.value,
                                        )
                                    }
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label htmlFor="additional_kwargs_schema">
                                Additional params (JSON)
                            </Label>
                            <textarea
                                id="additional_kwargs_schema"
                                className="flex min-h-28 w-full rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                                value={form.additional_kwargs_schema}
                                onChange={(e) =>
                                    setField(
                                        "additional_kwargs_schema",
                                        e.target.value,
                                    )
                                }
                            />
                        </div>

                        {formError && (
                            <Alert variant="destructive">
                                <AlertDescription>{formError}</AlertDescription>
                            </Alert>
                        )}
                    </div>

                    <DialogFooter>
                        <Button
                            variant="outline"
                            onClick={() => setDialogOpen(false)}
                            disabled={saving}
                        >
                            Cancel
                        </Button>
                        <Button onClick={handleSave} disabled={saving}>
                            {saving ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                                "Save"
                            )}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
