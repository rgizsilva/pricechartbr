/**
 * src/routes/admin.tsx — substituição da versão mock
 *
 * Diferenças vs original:
 *  - Lê dados reais via fetchStats() e fetchWatchlist() da API
 *  - CRUD de termos de busca: adicionar, ativar/pausar, remover
 *  - Tabela de vendas recentes com preço e data reais
 */
import { createFileRoute } from "@tanstack/react-router";
import {
  Plus, Package, Tag, BarChart3, Clock, Loader2, Trash2, Power,
} from "lucide-react";
import { toast } from "sonner";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatCard } from "@/components/stat-card";
import { TimeAgo } from "@/components/time-ago";
import {
  fetchStats, fetchWatchlist, createWatchlistTerm,
  toggleWatchlistTerm, deleteWatchlistTerm,
  formatPrice,
  type Stats, type SearchQuery,
} from "@/lib/api";

export const Route = createFileRoute("/admin")({
  head: () => ({ meta: [{ title: "Admin — PREÇORAMA" }] }),
  component: Admin,
});

function Admin() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [watchlist, setWatchlist] = useState<SearchQuery[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    try {
      const [s, w] = await Promise.all([fetchStats(), fetchWatchlist()]);
      setStats(s);
      setWatchlist(w);
    } catch (e) {
      toast.error("Erro ao carregar dados da API.");
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <div>
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-primary">
          Painel de controle
        </p>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight">Admin</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Gerencie termos monitorados e visualize vendas capturadas.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label="Anúncios totais"
          value={String(stats?.total ?? 0)}
          icon={Package}
          accent="primary"
        />
        <StatCard
          label="Termos ativos"
          value={String(watchlist.filter((w) => w.ativo).length)}
          icon={Tag}
        />
        <StatCard
          label="Vendidos"
          value={String(stats?.fechados ?? 0)}
          icon={BarChart3}
          accent="gold"
        />
        <StatCard
          label="Preço médio venda"
          value={formatPrice(stats?.preco_medio_venda ?? null)}
          icon={Clock}
          hint={
            stats?.ultima_venda
              ? `Última: ${new Date(stats.ultima_venda).toLocaleDateString("pt-BR")}`
              : undefined
          }
        />
      </div>

      <Tabs defaultValue="watchlist">
        <TabsList>
          <TabsTrigger value="watchlist">Termos monitorados</TabsTrigger>
          <TabsTrigger value="vendas">Vendas recentes</TabsTrigger>
        </TabsList>

        {/* Tab: Watchlist (search_queries) */}
        <TabsContent value="watchlist" className="mt-4 space-y-4">
          <AddTermForm onAdd={reload} />

          <div className="overflow-hidden rounded-xl border border-border/60 bg-card/50 backdrop-blur">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Termo</th>
                  <th className="px-4 py-2.5 font-medium">Anúncios</th>
                  <th className="px-4 py-2.5 font-medium hidden md:table-cell">Última busca</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium text-right">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {watchlist.map((q) => (
                  <WatchlistRow key={q.id} query={q} onRefresh={reload} />
                ))}
                {watchlist.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                      Nenhum termo cadastrado. Adicione um acima.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>

        {/* Tab: Vendas recentes */}
        <TabsContent value="vendas" className="mt-4">
          <div className="overflow-hidden rounded-xl border border-border/60 bg-card/50 backdrop-blur">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Anúncio</th>
                  <th className="px-4 py-2.5 font-medium">Condição</th>
                  <th className="px-4 py-2.5 font-medium">Preço final</th>
                  <th className="px-4 py-2.5 font-medium text-right">Vendido em</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {(stats?.vendas_recentes ?? []).map((v) => (
                  <tr key={v.mlb_id} className="hover:bg-muted/20">
                    <td className="px-4 py-2.5">
                      <a
                        href={`https://produto.mercadolivre.com.br/${v.mlb_id.replace("MLB", "MLB-")}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium hover:text-primary hover:underline"
                      >
                        {v.titulo}
                      </a>
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground">{v.condicao ?? "—"}</td>
                    <td className="px-4 py-2.5 num font-semibold text-primary">
                      {formatPrice(v.preco_final)}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-muted-foreground">
                      {v.finalizado_em ? (
                        <TimeAgo iso={v.finalizado_em} />
                      ) : "—"}
                    </td>
                  </tr>
                ))}
                {(!stats?.vendas_recentes || stats.vendas_recentes.length === 0) && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                      Nenhuma venda registrada ainda.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Subcomponentes ──────────────────────────────────────────────

function AddTermForm({ onAdd }: { onAdd: () => void }) {
  const [termo, setTermo] = useState("");
  const [saving, setSaving] = useState(false);

  const handleAdd = async () => {
    if (!termo.trim()) {
      toast.error("Digite um termo para monitorar.");
      return;
    }
    setSaving(true);
    try {
      await createWatchlistTerm(termo.trim());
      toast.success(`Termo "${termo.trim()}" adicionado!`);
      setTermo("");
      onAdd();
    } catch (e) {
      toast.error("Erro ao adicionar termo.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex gap-2">
      <Input
        value={termo}
        onChange={(e) => setTermo(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleAdd()}
        placeholder="ex: zelda ocarina of time n64"
        className="flex-1"
        disabled={saving}
      />
      <Button onClick={handleAdd} disabled={saving} className="gradient-neon text-primary-foreground">
        {saving ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Plus className="h-4 w-4" />
        )}
        <span className="ml-1">Adicionar</span>
      </Button>
    </div>
  );
}

function WatchlistRow({
  query,
  onRefresh,
}: {
  query: SearchQuery;
  onRefresh: () => void;
}) {
  const [loading, setLoading] = useState(false);

  const handleToggle = async () => {
    setLoading(true);
    try {
      await toggleWatchlistTerm(query.id, !query.ativo);
      toast.success(query.ativo ? "Termo pausado." : "Termo reativado.");
      onRefresh();
    } catch {
      toast.error("Erro ao atualizar termo.");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Remover o termo "${query.termo}"? Os anúncios ficam no banco.`)) return;
    setLoading(true);
    try {
      await deleteWatchlistTerm(query.id);
      toast.success("Termo removido.");
      onRefresh();
    } catch {
      toast.error("Erro ao remover termo.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <tr className="hover:bg-muted/20">
      <td className="px-4 py-2.5 font-medium">{query.termo}</td>
      <td className="px-4 py-2.5 text-muted-foreground">
        <span className="num">{query.total_anuncios}</span>
        <span className="ml-1 text-xs">
          ({query.ativos} ativos · {query.fechados} vendidos)
        </span>
      </td>
      <td className="px-4 py-2.5 text-xs text-muted-foreground hidden md:table-cell">
        {query.ultima_busca ? (
          <TimeAgo iso={query.ultima_busca} />
        ) : (
          "Nunca"
        )}
      </td>
      <td className="px-4 py-2.5">
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
            query.ativo
              ? "bg-success/10 text-success"
              : "bg-muted text-muted-foreground"
          }`}
        >
          {query.ativo ? "Ativo" : "Pausado"}
        </span>
      </td>
      <td className="px-4 py-2.5 text-right">
        <Button
          variant="ghost"
          size="sm"
          disabled={loading}
          onClick={handleToggle}
          title={query.ativo ? "Pausar" : "Reativar"}
        >
          <Power className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={loading}
          onClick={handleDelete}
          title="Remover"
          className="text-destructive hover:text-destructive"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </td>
    </tr>
  );
}
