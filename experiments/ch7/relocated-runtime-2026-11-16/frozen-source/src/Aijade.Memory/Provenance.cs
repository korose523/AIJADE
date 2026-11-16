using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Hac;
using Aijade.Memory.Model;

namespace Aijade.Memory;

// v7 §27 evidence fabric: a logical provenance layer weaving the belief graph, episodes, facts, procedural and working
// memories and the §25 revision audit into one queryable graph (not a separate service), plus the two-level explanation:
// a one-line attribution, or the research view with the event chain, score decomposition, HAC state and policy chain.
// Read-only: it never decides retention or salience.

public enum ProvenanceKind
{
    Belief,
    BeliefRevision,
    Episode,
    Fact,
    Procedural,
    Working,
    Rejection,
}

public sealed record ProvenanceNode(string Ref, ProvenanceKind Kind, string Label, JsonObject Detail);

public sealed record ProvenanceEdge(string From, string To, string Relation);

public sealed record ProvenanceGraph(IReadOnlyList<ProvenanceNode> Nodes, IReadOnlyList<ProvenanceEdge> Edges)
{
    public const int Version = 1;
}

public abstract record Explanation;

public sealed record SimpleExplanation(string Text) : Explanation;

/// <summary>The research view: chain, score decomposition (only with a query), HAC state and the policy that produced it.</summary>
public sealed record ResearchExplanation(
    string Summary, IReadOnlyList<ProvenanceNode> Chain, ScoreParts? Scores, HacState? GatingZ, GatingCoefficients PolicyGating, HacConfig? PolicyHac) : Explanation;

public static class Provenance
{
    private static string Truncate(string s, int n = 40) => s.Length > n ? $"{s[..n]}…" : s;

    private static string Shorten(string s, int n = 60) => s.Length > n ? $"{s[..n]}…" : s;

    private static JsonArray Strings(IEnumerable<string> s) => new(s.Select(x => (JsonNode?)x).ToArray());

    /// <summary>The full provenance graph of the live store (the v7 §27 reverse-trace chain).</summary>
    public static ProvenanceGraph Build(BioticMemory mem)
    {
        var nodes = new List<ProvenanceNode>();
        var edges = new List<ProvenanceEdge>();
        foreach (var e in mem.Episodes)
        {
            nodes.Add(new(e.Id, ProvenanceKind.Episode, $"Episode: {Truncate(e.Content)}",
                new JsonObject { ["content"] = e.Content, ["tags"] = Strings(e.Context.Tags), ["salience"] = e.Encoding.Salience }));
        }
        foreach (var f in mem.Facts)
        {
            nodes.Add(new(f.Id, ProvenanceKind.Fact, $"Fact: {Truncate(f.Content)}", new JsonObject { ["content"] = f.Content, ["derivedFrom"] = Strings(f.DerivedFrom) }));
            edges.AddRange(f.DerivedFrom.Select(src => new ProvenanceEdge(f.Id, src, "distilled-from")));
        }
        foreach (var p in mem.Procedural)
            nodes.Add(new(p.Id, ProvenanceKind.Procedural, $"Procedural: {Truncate(p.Content)}", new JsonObject { ["content"] = p.Content, ["derivedFrom"] = p.DerivedFrom }));
        foreach (var w in mem.Working)
            nodes.Add(new(w.Id, ProvenanceKind.Working, $"Working: {Truncate(w.Content)}", new JsonObject { ["content"] = w.Content }));
        foreach (var b in mem.Beliefs)
        {
            nodes.Add(new(b.Id, ProvenanceKind.Belief, $"Belief: {Truncate(b.Proposition)}", new JsonObject
            {
                ["proposition"] = b.Proposition,
                ["status"] = WireName.Of(b.Status),
                ["owner"] = WireName.Of(b.Owner),
                ["confidence"] = b.Confidence,
            }));
            edges.AddRange(b.EvidenceIds.Select(ev => new ProvenanceEdge(b.Id, ev, "evidenced-by")));
            edges.AddRange(b.CounterEvidenceIds.Select(ce => new ProvenanceEdge(b.Id, ce, "contested-by")));
        }
        foreach (var r in mem.BeliefRevisions)
        {
            nodes.Add(new(r.Id, ProvenanceKind.BeliefRevision, $"Revision {r.Id}",
                new JsonObject { ["at"] = r.At, ["actor"] = r.Actor, ["rationale"] = r.Rationale, ["deltaLogit"] = r.DeltaLogit }));
            edges.Add(new(r.Id, r.BeliefId, "revision-of"));
        }
        for (var i = 0; i < mem.BeliefRejections.Count; i++)
        {
            var j = mem.BeliefRejections[i];
            nodes.Add(new($"rej_{JsFormat.Number(j.At)}_{i}", ProvenanceKind.Rejection, $"Rejected: {Truncate(j.Proposition)}",
                new JsonObject { ["proposition"] = j.Proposition, ["reason"] = j.Reason, ["at"] = j.At }));
        }
        return new ProvenanceGraph(nodes, edges);
    }

    /// <summary>Breadth-first walk upstream from <paramref name="targetRef"/> (target first, then its sources); cycles are guarded.</summary>
    public static IReadOnlyList<ProvenanceNode> Trace(ProvenanceGraph graph, string targetRef)
    {
        var byRef = new Dictionary<string, ProvenanceNode>(StringComparer.Ordinal);
        foreach (var n in graph.Nodes)
            byRef[n.Ref] = n;
        var outgoing = graph.Edges.GroupBy(e => e.From, StringComparer.Ordinal).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
        var chain = new List<ProvenanceNode>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var queue = new Queue<string>([targetRef]);
        while (queue.Count > 0)
        {
            var r = queue.Dequeue();
            if (!seen.Add(r))
                continue;
            if (byRef.TryGetValue(r, out var node))
                chain.Add(node);
            foreach (var e in outgoing.GetValueOrDefault(r) ?? [])
            {
                if (!seen.Contains(e.To))
                    queue.Enqueue(e.To);
            }
        }
        return chain;
    }

    /// <summary>The two-level explanation (v7 §27); a query adds the score decomposition for memory refs.</summary>
    public static Explanation Explain(string targetRef, bool research, BioticMemory mem, string? query = null)
    {
        var graph = Build(mem);
        var node = graph.Nodes.FirstOrDefault(n => n.Ref == targetRef);
        if (node is null)
        {
            var fallback = $"No provenance node found for \"{targetRef}\".";
            return research ? new ResearchExplanation(fallback, [], null, mem.HacState, mem.Config.Gating, mem.Config.Hac) : new SimpleExplanation(fallback);
        }
        if (!research)
            return new SimpleExplanation(SimpleText(node));
        var scores = query is null ? null : mem.ScoreCandidateById(query, targetRef)?.Parts;
        return new ResearchExplanation(SimpleText(node), Trace(graph, targetRef), scores, mem.HacState, mem.Config.Gating, mem.Config.Hac);
    }

    private static string Text(JsonNode? n) => n switch
    {
        JsonValue v when v.TryGetValue<string>(out var s) => s,
        JsonValue v => JsFormat.Number(Aijade.Core.Schema.WireSchema.NumberOf(v)),
        _ => "undefined",
    };

    private static string SimpleText(ProvenanceNode node) => node.Kind switch
    {
        ProvenanceKind.Belief => $"Belief \"{Shorten(Text(node.Detail["proposition"]))}\" — status={Text(node.Detail["status"])}, confidence={Text(node.Detail["confidence"])}.",
        ProvenanceKind.Episode => $"Episode \"{Shorten(Text(node.Detail["content"]))}\" was encoded (salience={Text(node.Detail["salience"])}).",
        ProvenanceKind.Fact => $"Fact \"{Shorten(Text(node.Detail["content"]))}\" distilled from {((JsonArray)node.Detail["derivedFrom"]!).Count} source episode(s).",
        _ => $"{WireName.Snake(node.Kind.ToString()).Replace('_', '-')} \"{Shorten(node.Label)}\".",
    };
}
