using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Learning.Skills;
using Aijade.Providers.Llm;

namespace Aijade.Learning.Forge;

// The skill forge — detect a teachable
// moment in a finished conversation, author a skill from the draft (with one self-repair pass), validate it structurally
// and with an LLM reviewer, evolve it from feedback, and keep it in a measured registry backed by the skill-library metrics.

public static class SkillPrompts
{
    private const string AuthoringStandards = """
        Follow the skill-authoring standards EXACTLY:
        - name: lowercase-hyphenated, <=64 chars, no spaces.
        - description: ONE sentence, <=60 characters, ends with a period. State the capability, not the implementation. No marketing words.
        - version: "0.1.0"
        - author: "AIJADE"
        - platforms: only if OS-bound (windows/linux/macos); omit for portable skills.
        - metadata.tags: a few Capitalized, Relevant tags.
        Body sections (in order): title (H1), intro (2-3 sentences), "When to Use" (bullet triggers), "Prerequisites" (env/creds), "How to Run" (canonical invocation), "Quick Reference" (flat list), "Procedure" (numbered steps, copy-paste exact), "Pitfalls" (known limits), "Verification" (one proof command).
        Never invent commands, paths, or APIs you were not given. Keep it scannable (~100-200 lines).
        """;

    public static string TeachableMoment(string history) => $"""
        You review a finished conversation to decide whether a REUSABLE skill should be distilled from it.
        A skill is worth creating when the conversation solved a non-trivial, repeatable task (a workflow, an API, a toolchain, a debugging recipe) — NOT for one-off chit-chat.

        CONVERSATION:
        {history}

        Decide: shouldCreate (boolean), a one-line rationale, and — only if shouldCreate — a draft with proposedName (lowercase-hyphenated), title, summary (<=60 char sentence ending with period), and whenToUse (bullet trigger phrases).
        """;

    public static string Generation(SkillDraft d) => $"""
        Author ONE complete skill from this draft. Output strict JSON: {"{"} "frontmatter": {"{"}...{"}"}, "body": {"{"}...{"}"} {"}"}.
        DRAFT:
        - proposedName: {d.ProposedName}
        - title: {d.Title}
        - summary: {d.Summary}
        - whenToUse: {string.Join("\n  - ", d.WhenToUse)}

        {AuthoringStandards}
        """;

    private static string Numbered(IReadOnlyList<string> steps) => string.Join("\n", steps.Select((s, i) => $"{i + 1}. {s}"));

    public static string Validation(SkillFrontmatter fm, SkillBody b) => $"""
        You are a skill reviewer. Inspect this skill and judge whether it is correct, self-contained, and safe to run.
        Flag: invented commands/paths/APIs, missing prerequisites, unverifiable steps, or a description that lies about the capability.
        Return strict JSON: {"{"} "ok": boolean, "warnings": string[], "score": number /*0..1*/ {"}"}.

        SKILL:
        name: {fm.Name}
        description: {fm.Description}
        {Numbered(b.Procedure)}
        verification: {b.Verification ?? "(none)"}
        whenToUse: {string.Join("; ", b.WhenToUse)}
        """;

    public static string Evolution(SkillFrontmatter fm, SkillBody b, string feedback) => $"""
        Improve the existing skill based on user feedback. Keep the same name. Rewrite ONLY what the feedback requires; do not churn unrelated sections.
        Return strict JSON of the FULL updated skill: {"{"} "frontmatter": {"{"}...{"}"}, "body": {"{"}...{"}"} {"}"}.

        FEEDBACK:
        {feedback}

        CURRENT SKILL:
        title: {b.Title}
        description: {fm.Description}
        procedure:
        {Numbered(b.Procedure)}
        pitfalls: {string.Join("; ", b.Pitfalls ?? [])}
        verification: {b.Verification ?? "(none)"}

        {AuthoringStandards}
        """;
}

/// <summary>A skill registry keyed by name that also keeps the measurable record (calls, verdicts, lifecycle) of each skill.</summary>
public interface IMeasuredSkillRegistry
{
    void Add(SkillPackage pkg);
    SkillPackage? Find(string name);
    bool Has(string name);
    IReadOnlyList<SkillPackage> List();
    bool Remove(string name);
    void RecordExecution(string name, ExecutionOutcome outcome);
    void SetSelfVerification(string name, SkillVerdict verdict, double? score = null, string? rationale = null, string? model = null);
    void Retire(string name, RetirementReason reason);
    SkillLibraryMetrics Metrics();
    IReadOnlyList<string> PruneLowPrecision(double threshold, int minCalls = 3);
    IReadOnlyList<SkillRecord> Records();
}

/// <summary>
/// In-memory measured registry; with a file it persists one JSON line per skill ({ record, pkg }) after every change.
/// Unlike the skill-forge-store registry, three failures retire a skill regardless of environment feedback.
/// </summary>
public sealed class MeasuredSkillRegistry : IMeasuredSkillRegistry
{
    private readonly OrderedDictionary<string, SkillPackage> _packages = new(StringComparer.Ordinal);
    private readonly OrderedDictionary<string, SkillRecord> _records = new(StringComparer.Ordinal);
    private readonly SkillDomain _domain;
    private readonly Func<double> _now;
    private readonly string? _file;

    private static readonly JsonSerializerOptions PkgJson = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
        Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter(JsonNamingPolicy.KebabCaseLower), new JsNumberJsonConverter() },
    };

    public MeasuredSkillRegistry(IEnumerable<SkillPackage>? initial = null, SkillDomain domain = SkillDomain.Synthetic, Func<double>? now = null, string? file = null)
    {
        _domain = domain;
        _now = now ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        _file = file;
        if (file is not null && File.Exists(file))
        {
            foreach (var line in File.ReadAllLines(file).Select(l => l.Trim()).Where(l => l.Length > 0))
            {
                var o = JsonNode.Parse(line)!;
                var record = JsonSerializer.Deserialize<SkillRecord>(o["record"]!.ToJsonString(), JsonlSkillStore.JsonOptions)!;
                _records[record.SkillId] = record;
                _packages[record.SkillId] = o["pkg"] is JsonObject p ? JsonSerializer.Deserialize<SkillPackage>(p.ToJsonString(), PkgJson)! : FromRecord(record);
            }
        }
        var seeded = false;
        foreach (var pkg in initial ?? [])
        {
            _packages[pkg.Frontmatter.Name] = pkg;
            _records[pkg.Frontmatter.Name] = ToRecord(pkg);
            seeded = true;
        }
        if (seeded)
            Persist();
    }

    private SkillRecord ToRecord(SkillPackage pkg) =>
        new(pkg.Frontmatter.Name, pkg.Frontmatter.Name, pkg.CreatedAt, _domain) { Body = JsonSerializer.Serialize(pkg.Body, PkgJson) };

    private static SkillPackage FromRecord(SkillRecord r) => new(
        new SkillFrontmatter(r.Name, "", "0.1.0", "AIJADE"),
        r.Body is { } b ? JsonSerializer.Deserialize<SkillBody>(b, PkgJson)! : new SkillBody(r.Name, [], []),
        r.CreatedAt, r.CreatedAt, SkillSource.HandAuthored, []);

    private void Persist()
    {
        if (_file is null)
            return;
        var lines = _records.Values.Select(r =>
        {
            var pkg = (_packages.GetValueOrDefault(r.SkillId) ?? FromRecord(r)) with { Module = null };
            return new JsonObject
            {
                ["record"] = JsonNode.Parse(JsonSerializer.Serialize(r, JsonlSkillStore.JsonOptions)),
                ["pkg"] = JsonNode.Parse(JsonSerializer.Serialize(pkg, PkgJson)),
            }.ToJsonString();
        }).ToList();
        if (Path.GetDirectoryName(Path.GetFullPath(_file)) is { } dir)
            Directory.CreateDirectory(dir);
        File.WriteAllText(_file, lines.Count > 0 ? string.Join("\n", lines) + "\n" : "");
    }

    public void Add(SkillPackage pkg)
    {
        _packages[pkg.Frontmatter.Name] = pkg;
        // In memory an existing record (and its counters) is kept.
        if (_file is not null || !_records.ContainsKey(pkg.Frontmatter.Name))
            _records[pkg.Frontmatter.Name] = ToRecord(pkg);
        Persist();
    }

    public SkillPackage? Find(string name) => _packages.GetValueOrDefault(name);

    public bool Has(string name) => _packages.ContainsKey(name);

    public IReadOnlyList<SkillPackage> List() => [.. _packages.Values];

    public IReadOnlyList<SkillRecord> Records() => [.. _records.Values];

    public bool Remove(string name)
    {
        var had = _packages.Remove(name);
        _records.Remove(name);
        if (had)
            Persist();
        return had;
    }

    public void RecordExecution(string name, ExecutionOutcome outcome)
    {
        if (_records.GetValueOrDefault(name) is not { } r)
            return;
        var calls = r.CallCount + 1;
        var successes = r.SuccessCount + (outcome.Ok ? 1 : 0);
        var ts = _now();
        var next = r with
        {
            CallCount = calls,
            SuccessCount = successes,
            FailureCount = r.FailureCount + (outcome.Ok ? 0 : 1),
            LastUsedAt = ts,
            Execution = new SkillExecution(outcome.Ok, ts, calls, string.IsNullOrEmpty(outcome.Detail) ? null : outcome.Detail, outcome.DurationMs),
        };
        _records[name] = calls >= 3 && successes == 0 && r.Status == SkillLifecycle.Active
            ? next with { Status = SkillLifecycle.Retired, RetirementReason = RetirementReason.LowPrecision, RetiredAt = ts }
            : next;
        Persist();
    }

    public void SetSelfVerification(string name, SkillVerdict verdict, double? score = null, string? rationale = null, string? model = null)
    {
        if (_records.GetValueOrDefault(name) is not { } r)
            return;
        var next = r with { SelfVerification = new SelfVerification(verdict, true, score, string.IsNullOrEmpty(rationale) ? null : rationale, string.IsNullOrEmpty(model) ? null : model) };
        _records[name] = verdict == SkillVerdict.Fail && r.Status == SkillLifecycle.Active
            ? next with { Status = SkillLifecycle.Rejected, RetirementReason = RetirementReason.SelfRejected, RetiredAt = _now() }
            : next;
        Persist();
    }

    public void Retire(string name, RetirementReason reason)
    {
        if (_records.GetValueOrDefault(name) is not { } r)
            return;
        _records[name] = r with { Status = reason == RetirementReason.SelfRejected ? SkillLifecycle.Rejected : SkillLifecycle.Retired, RetirementReason = reason, RetiredAt = _now() };
        Persist();
    }

    public SkillLibraryMetrics Metrics() => SkillMetrics.Compute([.. _records.Values]);

    public IReadOnlyList<string> PruneLowPrecision(double threshold, int minCalls = 3)
    {
        var ts = _now();
        var doomed = _records.Values.Where(r => r.Status == SkillLifecycle.Active && r.CallCount >= minCalls && (double)r.SuccessCount / r.CallCount < threshold).ToList();
        foreach (var r in doomed)
            _records[r.SkillId] = r with { Status = SkillLifecycle.Retired, RetirementReason = RetirementReason.LowPrecision, RetiredAt = ts };
        if (doomed.Count > 0)
            Persist();
        return doomed.Select(r => r.SkillId).ToList();
    }
}

/// <summary>A sandbox check run during validation; a failure halves the score and becomes an error.</summary>
public delegate Task<(bool Ok, string Notes)> SkillSandbox(SkillPackage pkg);

public sealed class SkillForge(IChatClient llm, IMeasuredSkillRegistry? registry = null, SkillSandbox? sandbox = null, Func<double>? now = null)
{
    private const string JsonOnly = "You output strict JSON only.";

    private readonly Func<double> _now = now ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());

    public IMeasuredSkillRegistry Registry { get; } = registry ?? new MeasuredSkillRegistry();

    private static ChatMessage[] Ask(string prompt) => [new(ChatRole.System, JsonOnly), new(ChatRole.User, prompt)];

    private static string History(IEnumerable<ChatMessage> history) => string.Join("\n\n", history.Select(m => $"{WireName.Of(m.Role)}: {m.Content}"));

    /// <summary>A draft when the conversation solved a repeatable task; null for chit-chat or an empty history.</summary>
    public async Task<SkillDraft?> DetectTeachableMomentAsync(IReadOnlyList<ChatMessage> history, CancellationToken ct = default)
    {
        var text = History(history);
        if (JsText.Trim(text).Length == 0)
            return null;
        var parsed = await llm.JsonCompleteAsync(Ask(SkillPrompts.TeachableMoment(text)), cancellationToken: ct).ConfigureAwait(false);
        if (parsed?["shouldCreate"] is not JsonValue sc || !sc.TryGetValue<bool>(out var should) || parsed["rationale"] is not JsonValue r || !r.TryGetValue<string>(out _))
            throw new SkillSchemaException(["teachable moment: expected { shouldCreate: boolean, rationale: string, draft? }"]);
        if (!should || parsed["draft"] is not JsonObject d)
            return null;
        try
        {
            return new SkillDraft(d["proposedName"]!.GetValue<string>(), d["title"]!.GetValue<string>(), d["summary"]!.GetValue<string>(),
                d["whenToUse"]!.AsArray().Select(x => x!.GetValue<string>()).ToList());
        }
        catch (Exception e) when (e is InvalidOperationException or NullReferenceException or FormatException)
        {
            throw new SkillSchemaException(["teachable moment: draft must have proposedName, title, summary, whenToUse[]"]);
        }
    }

    private async Task<SkillPackage> AttemptGenerateAsync(SkillDraft draft, IReadOnlyList<string>? priorErrors, CancellationToken ct)
    {
        var prompt = SkillPrompts.Generation(draft);
        if (priorErrors is { Count: > 0 })
            prompt += $"\n\nPREVIOUS ERRORS TO FIX:\n{string.Join("\n", priorErrors.Select(e => $"- {e}"))}";
        var (fm, body) = SkillSchema.Parse(await llm.JsonCompleteAsync(Ask(prompt), cancellationToken: ct).ConfigureAwait(false));
        var at = _now();
        return new SkillPackage(fm, body, at, at, SkillSource.LlmGenerated, []);
    }

    /// <summary>Author, validate, and if invalid try one repair with the errors; keep whichever scores higher.</summary>
    public async Task<SkillPackage> GenerateSkillAsync(SkillDraft draft, CancellationToken ct = default)
    {
        var first = await AttemptGenerateAsync(draft, null, ct).ConfigureAwait(false);
        var result = await ValidateSkillAsync(first, ct).ConfigureAwait(false);
        if (result.Ok)
            return first;
        var repaired = await AttemptGenerateAsync(draft, result.Errors, ct).ConfigureAwait(false);
        var recheck = await ValidateSkillAsync(repaired, ct).ConfigureAwait(false);
        return recheck.Score >= result.Score ? repaired : first;
    }

    /// <summary>
    /// Structural check (0.6 when valid), optional sandbox (failure halves the score), then the LLM reviewer:
    /// score = 0.5 + 0.5·review when structurally valid, else 0.3·review. A reviewer failure is a warning, not an error.
    /// </summary>
    public async Task<SkillValidationResult> ValidateSkillAsync(SkillPackage pkg, CancellationToken ct = default)
    {
        var errors = new List<string>(SkillSchema.Validate(SkillSchema.ToJson(pkg.Frontmatter, pkg.Body)));
        var warnings = new List<string>();
        var structuralOk = errors.Count == 0;
        var score = structuralOk ? 0.6 : 0;
        if (sandbox is not null)
        {
            try
            {
                var (ok, notes) = await sandbox(pkg).ConfigureAwait(false);
                if (!ok)
                {
                    errors.Add($"sandbox: {notes}");
                    score *= 0.5;
                }
                else
                {
                    warnings.Add($"sandbox: {notes}");
                }
            }
#pragma warning disable CA1031 // A sandbox that cannot run is reported, not fatal.
            catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
            {
                warnings.Add($"sandbox skipped: {e.Message}");
            }
        }
        try
        {
            var judge = await llm.JsonCompleteAsync(Ask(SkillPrompts.Validation(pkg.Frontmatter, pkg.Body)), cancellationToken: ct).ConfigureAwait(false);
            var ok = judge?["ok"]?.GetValue<bool>() ?? throw new SkillSchemaException(["ok: Invalid input: expected boolean"]);
            var reviewWarnings = judge["warnings"] as JsonArray ?? throw new SkillSchemaException(["warnings: Invalid input: expected array"]);
            var llmScore = judge["score"] is JsonValue sv ? double.Parse(sv.ToJsonString(), System.Globalization.CultureInfo.InvariantCulture) : throw new SkillSchemaException(["score: Invalid input: expected number"]);
            if (llmScore is < 0 or > 1)
                throw new SkillSchemaException(["score: out of range [0, 1]"]);
            warnings.AddRange(reviewWarnings.Select(w => w!.GetValue<string>()));
            score = structuralOk ? 0.5 + (llmScore * 0.5) : llmScore * 0.3;
            if (!ok && structuralOk)
                errors.Add("LLM reviewer judged the skill unsafe/incomplete.");
        }
#pragma warning disable CA1031 // A failed review is a warning.
        catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
        {
            warnings.Add($"LLM self-check skipped: {e.Message}");
        }
        return new SkillValidationResult(structuralOk && errors.Count == 0, errors, warnings, Math.Max(0, Math.Min(1, score)));
    }

    public static string BumpVersion(string v)
    {
        var parts = v.Split('.');
        return parts.Length == 3 && parts.All(p => p.Length > 0 && p.All(char.IsAsciiDigit))
            ? $"{parts[0]}.{parts[1]}.{JsFormat.Number(double.Parse(parts[2], System.Globalization.CultureInfo.InvariantCulture) + 1)}"
            : v;
    }

    /// <summary>Rewrite the skill from feedback; same name, patch version bumped, the change logged.</summary>
    public async Task<SkillPackage> EvolveSkillAsync(SkillPackage pkg, string feedback, CancellationToken ct = default)
    {
        var from = pkg.Frontmatter.Version;
        var to = BumpVersion(from);
        var (fm, body) = SkillSchema.Parse(await llm.JsonCompleteAsync(Ask(SkillPrompts.Evolution(pkg.Frontmatter, pkg.Body, feedback)), cancellationToken: ct).ConfigureAwait(false));
        var entry = new SkillEvolutionEntry(_now(), feedback, $"evolved {fm.Name} from {from} -> {to}", from, to);
        return new SkillPackage(fm with { Version = to }, body, pkg.CreatedAt, _now(), SkillSource.Evolved, [.. pkg.EvolutionLog, entry], pkg.Module);
    }

    /// <summary>Synchronous structural gate for registration; deep checks are ValidateSkillAsync's job.</summary>
    public (bool Registered, SkillValidationResult Result) Register(SkillPackage pkg)
    {
        var issues = SkillSchema.Validate(SkillSchema.ToJson(pkg.Frontmatter, pkg.Body));
        if (issues.Count > 0)
            return (false, new SkillValidationResult(false, issues, [], 0));
        Registry.Add(pkg);
        return (true, new SkillValidationResult(true, [], [], 0.6));
    }
}
