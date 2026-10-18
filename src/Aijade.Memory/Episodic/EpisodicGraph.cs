using Aijade.Memory.Contracts;

namespace Aijade.Memory.Episodic;

// v7 §10.1 episodic evidence graph — the "what happened" half of the dual-graph memory. Unlike the belief graph it never
// adjudicates a single fact: contradictory sources coexist. Two enforced invariants: no event without a source (§6,
// refusals are counted), and before/after edges stay acyclic.

public enum EpisodicEdgeKind
{
    ObservedIn,
    Involves,
    Before,
    After,
    CausedCandidate,
    ExpressedAs,
}

public sealed record EpisodicSource(string Id, bool Trusted, string? ContentDigest = null, string? ConsentPolicy = null);

public sealed record EpisodicEvent(string Id, string ContentRef, double OccurredAt);

public sealed record EpisodicEdge(EpisodicEdgeKind Kind, string From, string To, double CreatedAt, EpisodicSource? Source = null, double? Weight = null);

/// <summary>Sources of one event whose contents disagree. Both sides are kept.</summary>
public sealed record SourceContradiction(string EventId, IReadOnlyList<EpisodicSource> Sources);

public sealed class EpisodicGraph(TimeProvider? clock = null)
{
    private readonly TimeProvider _clock = clock ?? TimeProvider.System;
    private readonly List<EpisodicEvent> _events = [];
    private readonly Dictionary<string, EpisodicEvent> _index = [];
    private readonly List<EpisodicEdge> _edges = [];

    public int Size => _events.Count;

    /// <summary>Attempts to add an event without a source — §6 compliance is measured, not assumed.</summary>
    public int Refusals { get; private set; }

    public EpisodicEvent? Event(string id) => _index.GetValueOrDefault(id);

    public IReadOnlyList<EpisodicEvent> Events() => [.. _events];

    public IReadOnlyList<EpisodicEdge> AllEdges() => [.. _edges];

    public Validation AddEvent(EpisodicEvent e, IReadOnlyList<EpisodicSource> sources)
    {
        if (_index.ContainsKey(e.Id))
            return Validation.Fail($"Episodic event \"{e.Id}\" already present");
        if (sources.Count == 0)
        {
            Refusals++;
            return Validation.Fail("Episodic event requires ≥1 observed_in source (v7 §6 traceability)");
        }
        _index[e.Id] = e;
        _events.Add(e);
        foreach (var s in sources)
            Attach(e.Id, s);
        return Validation.Pass;
    }

    /// <summary>Add corroborating (or, with a different digest, contradicting) evidence; never overwrites.</summary>
    public Validation AddSource(string eventId, EpisodicSource source)
    {
        if (!_index.ContainsKey(eventId))
            return Validation.Fail($"Unknown episodic event \"{eventId}\"");
        Attach(eventId, source);
        return Validation.Pass;
    }

    private void Attach(string eventId, EpisodicSource source) =>
        _edges.Add(new EpisodicEdge(EpisodicEdgeKind.ObservedIn, eventId, source.Id, _clock.GetUtcNow().ToUnixTimeMilliseconds(), source));

    private static bool IsTemporal(EpisodicEdgeKind k) => k is EpisodicEdgeKind.Before or EpisodicEdgeKind.After;

    /// <summary>Normalise a temporal edge to (earlier, later).</summary>
    private static (string Earlier, string Later)? Normalize(EpisodicEdge e) => e.Kind switch
    {
        EpisodicEdgeKind.Before => (e.From, e.To),
        EpisodicEdgeKind.After => (e.To, e.From),
        _ => null,
    };

    public Validation AddEdge(EpisodicEdge edge)
    {
        if (!Enum.IsDefined(edge.Kind))
            return Validation.Fail($"Unknown episodic edge kind \"{edge.Kind}\"");
        if (!_index.ContainsKey(edge.From))
            return Validation.Fail($"Unknown source event \"{edge.From}\"");
        if (IsTemporal(edge.Kind))
        {
            if (!_index.ContainsKey(edge.To))
                return Validation.Fail($"Temporal edge requires a known target event, got \"{edge.To}\"");
            if (edge.From == edge.To)
                return Validation.Fail("Temporal self-loop is meaningless");
            if (Normalize(edge) is var (earlier, later) && Reachable(later, earlier))
                return Validation.Fail("Temporal edge would create a cycle (before/after must stay acyclic)");
        }
        _edges.Add(edge);
        return Validation.Pass;
    }

    private bool Reachable(string from, string to)
    {
        var adj = new Dictionary<string, List<string>>();
        foreach (var e in _edges)
        {
            if (Normalize(e) is not var (a, b))
                continue;
            if (!adj.TryGetValue(a, out var list))
                adj[a] = list = [];
            list.Add(b);
        }
        var seen = new HashSet<string> { from };
        var queue = new Queue<string>([from]);
        while (queue.Count > 0)
        {
            var cur = queue.Dequeue();
            if (cur == to)
                return true;
            foreach (var next in adj.GetValueOrDefault(cur) ?? [])
            {
                if (seen.Add(next))
                    queue.Enqueue(next);
            }
        }
        return false;
    }

    public IReadOnlyList<EpisodicSource> SourcesOf(string eventId) =>
        _edges.Where(e => e.Kind == EpisodicEdgeKind.ObservedIn && e.From == eventId && e.Source is not null).Select(e => e.Source!).ToList();

    public IReadOnlyList<EpisodicEdge> EdgesFrom(string eventId, EpisodicEdgeKind? kind = null) =>
        _edges.Where(e => e.From == eventId && (kind is null || e.Kind == kind)).ToList();

    /// <summary>Candidate causes only — whether they hold is tested by CBR (ITE), not asserted here.</summary>
    public IReadOnlyList<string> CausalCandidates(string eventId) => Targets(eventId, EpisodicEdgeKind.CausedCandidate);

    public IReadOnlyList<string> ExpressionsOf(string eventId) => Targets(eventId, EpisodicEdgeKind.ExpressedAs);

    public IReadOnlyList<string> EntitiesOf(string eventId) => Targets(eventId, EpisodicEdgeKind.Involves);

    private List<string> Targets(string eventId, EpisodicEdgeKind kind) =>
        _edges.Where(e => e.Kind == kind && e.From == eventId).Select(e => e.To).ToList();

    /// <summary>Share of events with ≥1 source (1 by construction; the real compliance signal is <see cref="Refusals"/>).</summary>
    public double TraceabilityRate() =>
        _events.Count == 0 ? 1 : (double)_events.Count(e => SourcesOf(e.Id).Count > 0) / _events.Count;

    /// <summary>Events whose sources carry different content digests. Both sides are kept, neither is adjudicated.</summary>
    public IReadOnlyList<SourceContradiction> Contradictions()
    {
        var output = new List<SourceContradiction>();
        foreach (var e in _events)
        {
            var sources = SourcesOf(e.Id);
            var digests = sources.Where(s => s.ContentDigest is not null).Select(s => s.ContentDigest!).ToHashSet();
            if (digests.Count > 1)
                output.Add(new SourceContradiction(e.Id, sources));
        }
        return output;
    }

    /// <summary>Topological order from before/after (ties: occurredAt, then id ordinal); null if a cycle exists.</summary>
    public IReadOnlyList<string>? TemporalOrder()
    {
        var indeg = _events.ToDictionary(e => e.Id, _ => 0);
        var adj = _events.ToDictionary(e => e.Id, _ => new List<string>());
        foreach (var e in _edges)
        {
            if (Normalize(e) is not var (a, b) || !indeg.ContainsKey(a) || !indeg.ContainsKey(b))
                continue;
            adj[a].Add(b);
            indeg[b]++;
        }
        var ready = _events.Where(e => indeg[e.Id] == 0).Select(e => e.Id).ToList();
        var order = new List<string>();
        while (ready.Count > 0)
        {
            ready = ready.OrderBy(x => _index[x].OccurredAt).ThenBy(x => x, StringComparer.Ordinal).ToList();
            var cur = ready[0];
            ready.RemoveAt(0);
            order.Add(cur);
            foreach (var next in adj[cur])
            {
                if (--indeg[next] == 0)
                    ready.Add(next);
            }
        }
        return order.Count == _events.Count ? order : null;
    }
}
