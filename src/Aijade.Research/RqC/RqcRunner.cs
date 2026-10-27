using System.Diagnostics;
using System.Globalization;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Research.SkillBench;
using Aijade.Research.Statistics;

namespace Aijade.Research.RqC;

// One RQ-C run writes
// <out>/<runId>/{trials.jsonl, summary.json}, stamped with the run fingerprint and git commit.

public enum RqcBackendKind
{
    Mock,
    Ollama,
}

/// <summary>Run configuration; defaults are the protocol fixed before the runs (<see cref="Preregistration"/>). The Ollama timeout is infrastructure, not part of the fingerprint.</summary>
public sealed record RqcCliConfig
{
    public int Trials { get; init; } = Preregistration.Trials;
    public uint Seed { get; init; } = Preregistration.Seed;
    public RqcBackendKind Backend { get; init; } = RqcBackendKind.Mock;
    public string? Model { get; init; }
    public int Rounds { get; init; } = Preregistration.Rounds;
    public double PCorrect { get; init; } = 0.5;
    public int Tasks { get; init; } = Preregistration.NTasks;
    public string Out { get; init; } = "experiments/rq-c";
    public double PruneThreshold { get; init; } = Preregistration.PruneThreshold;
    public int PruneMinCalls { get; init; } = Preregistration.PruneMinCalls;
    public string OllamaBaseUrl { get; init; } = "http://localhost:11434";
    public int? TimeoutMs { get; init; }
    public bool Overwrite { get; init; }

    /// <summary>
    /// Send one discarded request before the run so the model is loaded (author decision, 2026-10-09): on Ollama the first
    /// greedy request after a model load differs from every later one. Infrastructure, not part of the fingerprint.
    /// </summary>
    public bool WarmUp { get; init; } = true;

    /// <summary>
    /// Also write candidates.jsonl: per step, the executed code, the raw generation and the self-verification rationale, so that
    /// every verdict can be re-checked offline (e.g. in another sandbox). Diagnostic output, not part of the fingerprint.
    /// </summary>
    public bool SaveCandidates { get; init; }

    /// <summary>
    /// Sampling temperature. The pre-registered design is greedy decoding (0); any other value is an exploratory
    /// sensitivity run: it enters the fingerprint and the run id, and is reported as a pre-registration deviation.
    /// </summary>
    public double Temperature { get; init; }

    /// <summary>
    /// Upper bound on the tokens of one reply (Ollama <c>num_predict</c>); none by default, as in the pre-registered runs. With
    /// context shifting a model can generate without end under greedy decoding; a reply that reaches the bound counts as no
    /// answer, like a repetition abort. It enters the fingerprint (but not the run id) when set.
    /// </summary>
    public int? MaxReplyTokens { get; init; }

    /// <summary>
    /// Read the last explicit "verdict: PASS|FAIL" of a verifier reply that does not begin with PASS or FAIL (the pre-registered
    /// rule counts such a reply as FAIL). Replies that begin with PASS or FAIL are read as before. Off by default; it enters
    /// the fingerprint (but not the run id) when set.
    /// </summary>
    public bool VerdictFallback { get; init; }

    /// <summary>
    /// Context window sent to Ollama (<c>num_ctx</c>); none by default, which on the Ollama 0.35 host of the earlier runs meant
    /// 4096. Newer servers load a model's full native context instead (131072 for Llama 3.1), so a run on such a server sets
    /// it explicitly. It enters the fingerprint (but not the run id) when set.
    /// </summary>
    public int? NumCtx { get; init; }

    /// <summary>
    /// Verifier prompt: "A" is the pre-registered one, "B" the alternative of the prompt-template control. B enters the
    /// fingerprint (but not the run id).
    /// </summary>
    public string VerifyTemplate { get; init; } = "A";

    /// <summary>
    /// candidates.jsonl of an interrupted run with the same configuration: its generations and self-verification replies are
    /// replayed before the live backend takes over. Infrastructure (reported in the summary), not part of the fingerprint.
    /// </summary>
    public string? ResumeFrom { get; init; }

    /// <summary>
    /// Negative control: the generator never sees the feedback (each task's first generation is returned for every later
    /// attempt), so neither factor has a causal path to the outcome and the degeneracy guard must call the run a
    /// constructive zero. A different experiment: it enters the fingerprint and the run id.
    /// </summary>
    public bool Inert { get; init; }

    public string RunId => $"rq-c-s{Seed}-{WireName.Of(Backend)}-t{Trials}-r{Rounds}" + (Temperature != 0 ? $"-T{JsFormat.Number(Temperature)}" : "") + (Inert ? "-INERT" : "");

    /// <summary>Parse the CLI flags; unknown flags and missing values are errors.</summary>
    public static RqcCliConfig Parse(IReadOnlyList<string> argv)
    {
        var cfg = new RqcCliConfig();
        for (var i = 0; i < argv.Count; i++)
        {
            var a = argv[i];
            string Next() => i + 1 < argv.Count ? argv[++i] : throw new ArgumentException($"Missing value for {a}");
            int Int() => int.Parse(Next(), CultureInfo.InvariantCulture);
            double Dbl() => double.Parse(Next(), CultureInfo.InvariantCulture);
            cfg = a switch
            {
                "--trials" => cfg with { Trials = Int() },
                "--seed" => cfg with { Seed = uint.Parse(Next(), CultureInfo.InvariantCulture) },
                "--backend" => cfg with { Backend = Next() switch { "mock" => RqcBackendKind.Mock, "ollama" => RqcBackendKind.Ollama, _ => throw new ArgumentException("--backend must be 'mock' or 'ollama'") } },
                "--model" => cfg with { Model = Next() },
                "--rounds" => cfg with { Rounds = Int() },
                "--p-correct" => cfg with { PCorrect = Dbl() },
                "--tasks" => cfg with { Tasks = Int() },
                "--out" => cfg with { Out = Next() },
                "--prune-threshold" => cfg with { PruneThreshold = Dbl() },
                "--min-calls" => cfg with { PruneMinCalls = Int() },
                "--ollama-base-url" => cfg with { OllamaBaseUrl = Next() },
                "--timeout-ms" => cfg with { TimeoutMs = Int() },
                "--overwrite" => cfg with { Overwrite = true },
                "--no-warmup" => cfg with { WarmUp = false },
                "--save-candidates" => cfg with { SaveCandidates = true },
                "--temperature" => cfg with { Temperature = Dbl() },
                "--resume-from" => cfg with { ResumeFrom = Next() },
                "--inert" => cfg with { Inert = true },
                "--max-reply-tokens" => cfg with { MaxReplyTokens = Int() },
                "--verdict-fallback" => cfg with { VerdictFallback = true },
                "--num-ctx" => cfg with { NumCtx = Int() },
                "--verify-template" => cfg with { VerifyTemplate = Next() },
                _ => throw new ArgumentException($"Unknown argument: {a}"),
            };
        }
        if (cfg.Backend == RqcBackendKind.Ollama && cfg.Model is null)
            throw new ArgumentException("--backend ollama requires --model");
        if (cfg.TimeoutMs is <= 0)
            throw new ArgumentException("--timeout-ms must be a positive integer");
        if (cfg.MaxReplyTokens is <= 0)
            throw new ArgumentException("--max-reply-tokens must be a positive integer");
        if (cfg.VerifyTemplate is not ("A" or "B"))
            throw new ArgumentException("--verify-template must be A or B");
        if (cfg.VerifyTemplate == "B" && cfg.Backend != RqcBackendKind.Ollama)
            throw new ArgumentException("--verify-template applies to the ollama backend only");
        if (cfg.NumCtx is <= 0)
            throw new ArgumentException("--num-ctx must be a positive integer");
        if (cfg.NumCtx is not null && cfg.Backend != RqcBackendKind.Ollama)
            throw new ArgumentException("--num-ctx applies to the ollama backend only");
        if (cfg.VerdictFallback && cfg.Backend != RqcBackendKind.Ollama)
            throw new ArgumentException("--verdict-fallback applies to the ollama backend only");
        if (cfg.MaxReplyTokens is not null && cfg.Backend != RqcBackendKind.Ollama)
            throw new ArgumentException("--max-reply-tokens applies to the ollama backend only");
        if (cfg.Temperature is < 0 or > 2)
            throw new ArgumentException("--temperature must be between 0 and 2");
        if (cfg.Temperature != 0 && cfg.Backend != RqcBackendKind.Ollama)
            throw new ArgumentException("--temperature applies to the ollama backend only");
        return cfg;
    }

    internal JsonObject ConfigJson()
    {
        var c = new JsonObject
        {
            ["trials"] = Trials,
            ["seed"] = Seed,
            ["backend"] = WireName.Of(Backend),
            ["model"] = Model,
            ["rounds"] = Rounds,
            ["pCorrect"] = PCorrect,
            ["tasks"] = Tasks,
            ["pruneThreshold"] = PruneThreshold,
            ["pruneMinCalls"] = PruneMinCalls,
            ["domain"] = "executable",
        };
        // Greedy runs keep the base fingerprint; a sampled run is a different experiment.
        if (Temperature != 0)
            c["temperature"] = Temperature;
        if (Inert)
            c["inert"] = true;
        if (MaxReplyTokens is { } m)
            c["maxReplyTokens"] = m;
        if (VerdictFallback)
            c["verdictFallback"] = true;
        if (NumCtx is { } ctx)
            c["numCtx"] = ctx;
        if (VerifyTemplate != "A")
            c["verifyTemplate"] = VerifyTemplate;
        return c;
    }

    /// <summary>FNV-1a of the design parameters serialized with keys sorted — identifies "the same experiment".</summary>
    public string Fingerprint()
    {
        var c = ConfigJson();
        var sorted = new JsonObject();
        foreach (var k in c.Select(kv => kv.Key).Order(StringComparer.Ordinal))
            sorted[k] = c[k]?.DeepClone();
        return JsFormat.Fnv1a(JsFormat.Stringify(sorted));
    }

    /// <summary>The seed handed to Ollama, derived from the master seed so a given --seed reproduces.</summary>
    public uint SamplingSeed => Backend == RqcBackendKind.Ollama ? unchecked((Seed ^ 0x9E3779B9u) * 0x85EBCA6Bu) : Seed;
}

public static class RqcRunner
{
    public const string HelpText = """
        RQ-C 2x2 harness

          --trials N        trials per condition (default 30)
          --seed N          master seed (default 42)
          --backend mock|ollama
          --model NAME      Ollama model (required for ollama)
          --rounds N        task-revisit rounds (default 5)
          --p-correct P     mock P(correct generation) (default 0.5)
          --tasks N         distinct tasks per trial (default 12)
          --out DIR         output directory (default experiments/rq-c)
          --prune-threshold P   prune precision threshold (default 0.5)
          --min-calls N     min calls before pruning (default 3)
          --ollama-base-url URL   (default http://localhost:11434)
          --timeout-ms N    per-request Ollama timeout in ms (default 120000; not part of the fingerprint)
          --overwrite       replace artifacts already in <out>/<runId> (refused by default)
          --no-warmup       skip the discarded warm-up request sent before an Ollama run
          --temperature T   sampling temperature (default 0, the pre-registered value; others are exploratory)
          --save-candidates write candidates.jsonl (code, raw generation, self-verification rationale per step)
          --resume-from F   replay the generations and verdicts in candidates.jsonl F of an interrupted run, then go live
          --max-reply-tokens N   cap one reply at N tokens (default none); a reply at the cap counts as no answer
          --verdict-fallback     read the last "verdict: PASS|FAIL" of a verifier reply that does not begin with PASS or FAIL
          --num-ctx N            context window sent to Ollama (default: the server's)
          --verify-template A|B  verifier prompt (default A, the pre-registered one)

        """;

    private static readonly string[] ArtifactNames = ["trials.jsonl", "summary.json"];

    /// <summary>
    /// The JSON lines of an interrupted run's record. A killed run can leave its last line half written; that line is
    /// dropped. A malformed line anywhere else is an error.
    /// </summary>
    public static List<JsonObject> ReadRecord(string path)
    {
        var lines = File.ReadAllLines(path).Where(l => l.Length > 0).ToList();
        var rows = new List<JsonObject>(lines.Count);
        for (var i = 0; i < lines.Count; i++)
        {
            try
            {
                rows.Add(JsonNode.Parse(lines[i])!.AsObject());
            }
            catch (System.Text.Json.JsonException) when (i == lines.Count - 1)
            {
                // the half-written last line of a killed run
            }
        }
        return rows;
    }

    /// <summary>
    /// The code commit the run is made from: <c>AIJADE_GIT_COMMIT</c> when set (for runs from a copy that is not a git
    /// checkout, such as a remote GPU host), otherwise the current commit, or "unknown" outside a git checkout.
    /// </summary>
    public static string GitHash()
    {
        var pinned = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT");
        if (!string.IsNullOrWhiteSpace(pinned))
            return pinned.Trim();
        try
        {
            using var p = Process.Start(new ProcessStartInfo("git", "rev-parse HEAD") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false });
            var s = p!.StandardOutput.ReadToEnd().Trim();
            p.WaitForExit();
            return p.ExitCode == 0 && s.Length > 0 ? s : "unknown";
        }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            return "unknown";
        }
    }

    internal static JsonObject StepJson(HarnessStep s) => new()
    {
        ["condition"] = s.Condition,
        ["trial"] = s.Trial,
        ["round"] = s.Round,
        ["taskId"] = s.TaskId,
        ["skillId"] = s.SkillId,
        ["reused"] = s.Reused,
        ["attempt"] = s.Attempt,
        ["hadEnvFeedback"] = s.HadEnvFeedback,
        ["hadSelfCritique"] = s.HadSelfCritique,
        ["regeneratedFromFailure"] = s.RegeneratedFromFailure,
        ["selfVerdict"] = s.SelfVerdictPass is { } p ? (p ? "pass" : "fail") : null,
        ["execOk"] = s.ExecOk,
        ["codeHash"] = s.Code is { } code ? JsFormat.Fnv1a(code) : null,
        ["durationMs"] = s.DurationMs,
    };

    /// <summary>Run one experiment and write its artifacts; refuses to overwrite existing results unless asked.</summary>
    public static async Task<(string OutDir, JsonObject Summary)> RunAsync(RqcCliConfig cfg, HttpClient? http = null, TextWriter? log = null, string? gitHash = null, CancellationToken ct = default)
    {
        var outDir = Path.GetFullPath(Path.Combine(cfg.Out, cfg.RunId));
        var existing = ArtifactNames.Where(n => new FileInfo(Path.Combine(outDir, n)) is { Exists: true, Length: > 0 }).ToList();
        if (existing.Count > 0 && !cfg.Overwrite)
            throw new IOException($"{outDir} already holds {string.Join(", ", existing)}; choose another --out, or pass --overwrite to replace them");
        Directory.CreateDirectory(outDir);
        var trialsPath = Path.Combine(outDir, "trials.jsonl");

        var sandbox = new Sandbox();
        // No client-wide timeout: the per-request --timeout-ms governs (HttpClient's default of 100 s used to cut it short).
        using var ownedHttp = http is null && cfg.Backend == RqcBackendKind.Ollama ? new HttpClient { Timeout = Timeout.InfiniteTimeSpan } : null;
        var client = http ?? ownedHttp;
        ILlmBackend backend = cfg.Backend == RqcBackendKind.Ollama
            ? new OllamaBackend(client!, cfg.Model!, cfg.OllamaBaseUrl, cfg.Temperature, cfg.SamplingSeed, TimeSpan.FromMilliseconds(cfg.TimeoutMs ?? 120_000), cfg.MaxReplyTokens, cfg.VerdictFallback, cfg.NumCtx, cfg.VerifyTemplate)
            : new MockBackend(cfg.Seed, sandbox, cfg.PCorrect);
        var liveOllama = backend as OllamaBackend;   // kept for the summary; the inert and resuming wrappers hide it
        var version = cfg.Backend == RqcBackendKind.Ollama ? await OllamaBackend.VersionAsync(client!, cfg.OllamaBaseUrl, ct).ConfigureAwait(false) : null;
        var digest = cfg.Backend == RqcBackendKind.Ollama && cfg.Model is { } model ? await OllamaBackend.DigestAsync(client!, cfg.OllamaBaseUrl, model, ct).ConfigureAwait(false) : null;
        var warmedUp = false;
        if (backend is OllamaBackend ollama && cfg.WarmUp)
        {
            await ollama.WarmUpAsync(ct).ConfigureAwait(false);
            warmedUp = true;
            log?.WriteLine("[warm-up] model loaded; first-request output discarded");
        }

        if (cfg.Inert)
        {
            backend = new InertBackend(backend);
            log?.WriteLine("[inert] negative control: the generator ignores all feedback");
        }
        ResumingBackend? resuming = null;
        List<JsonObject>? recorded = null;
        if (cfg.ResumeFrom is { } resumeFrom)
        {
            // read everything before candidates.jsonl in the output directory is reopened for writing
            recorded = ReadRecord(resumeFrom);
            // the logged self-verdicts come from the interrupted run's trials.jsonl beside its candidates.jsonl
            var logged = ReadRecord(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(resumeFrom))!, "trials.jsonl")).Select(l => l["selfVerdict"]).ToList();
            if (logged.Count < recorded.Count)
            {
                // the two files of a killed run can end at different steps; only steps present in both are replayed
                log?.WriteLine($"[resume] trials.jsonl ends at step {logged.Count}, candidates.jsonl at {recorded.Count}: replaying the first {logged.Count}");
                recorded = [.. recorded.Take(logged.Count)];
            }
            var generations = recorded.Where(c => c["reused"]?.GetValue<bool>() == false).Select(c => c["generation"]!.GetValue<string>()).ToList();
            var verdicts = recorded.Select((c, i) => (c, i)).Where(x => x.c["selfRationale"] is not null)
                .Select(x => (logged[x.i]!.GetValue<bool>(), x.c["selfRationale"]!.GetValue<string>())).ToList();
            backend = resuming = new ResumingBackend(backend, generations, verdicts);
            log?.WriteLine($"[resume] replaying {recorded.Count} steps ({generations.Count} generations, {verdicts.Count} verdicts) from {resumeFrom}");
        }

        var steps = new List<StepRecord>();
        var clock = Stopwatch.StartNew();
        await using var candidates = cfg.SaveCandidates ? new StreamWriter(Path.Combine(outDir, "candidates.jsonl"), false, new System.Text.UTF8Encoding(false)) : null;
        await using (var writer = new StreamWriter(trialsPath, false, new System.Text.UTF8Encoding(false)))
        {
            await Harness.RunAsync(new RunOptions(backend, cfg.Trials, cfg.Rounds, cfg.Seed, cfg.Tasks, sandbox, cfg.PruneThreshold, cfg.PruneMinCalls, () => 0, step =>
            {
                var line = JsFormat.Stringify(StepJson(step));
                writer.Write(line + "\n");
                if (recorded is not null && steps.Count < recorded.Count)
                {
                    // the replayed prefix must reproduce the interrupted run step for step
                    var r = recorded[steps.Count];
                    if (r["skillId"]?.GetValue<string>() != step.SkillId || r["execOk"]?.GetValue<bool>() != step.ExecOk || r["reused"]?.GetValue<bool>() != step.Reused)
                        throw new InvalidOperationException($"resume diverged at step {steps.Count}: recorded {r["skillId"]}, replayed {step.SkillId}");
                }
                var candidate = new JsonObject
                {
                    ["step"] = steps.Count,
                    ["skillId"] = step.SkillId,
                    ["reused"] = step.Reused,
                    ["execOk"] = step.ExecOk,
                    ["code"] = step.Code,
                    ["generation"] = step.Generation,
                    ["selfRationale"] = step.SelfRationale,
                };
                if (step.SelfReply is not null)
                    candidate["selfReply"] = step.SelfReply;   // the whole verifier reply when the rationale is truncated
                candidates?.Write(candidate.ToJsonString() + "\n");
                // every step reaches the disk before the next one starts, so a killed run loses at most the step in flight
                writer.Flush();
                candidates?.Flush();
                steps.Add(StepRecord.Parse(line));
                if (steps.Count % 200 == 0)
                {
                    var secs = clock.Elapsed.TotalSeconds;
                    log?.WriteLine($"[progress] {steps.Count} steps  {JsFormat.ToFixed(secs, 0)}s  {JsFormat.ToFixed(steps.Count / secs, 2)} steps/s");
                }
            }), ct).ConfigureAwait(false);
        }

        var analysis = RqcAnalysis.Analyze(steps, new RqcConfig(cfg.Seed, cfg.PruneThreshold, cfg.PruneMinCalls));
        var mock = cfg.Backend == RqcBackendKind.Mock;
        var summary = new JsonObject { ["mode"] = mock ? "simulation" : "live" };
        if (mock)
            summary["simulationNote"] = "Mock backend: injected hallucination=0.30, miss=0.10. These validate the estimator, not the phenomenon. Do not cite as empirical.";
        summary["config"] = cfg.ConfigJson();
        summary["sampling"] = new JsonObject
        {
            ["mode"] = mock ? "simulation" : "live",
            ["model"] = mock ? null : cfg.Model,
            ["temperature"] = mock ? null : cfg.Temperature,
            ["seed"] = cfg.SamplingSeed,
            ["ollamaVersion"] = version,
        };
        if (!mock)
        {
            summary["sampling"]!["modelDigest"] = digest;
            if (liveOllama is not null)
            {
                summary["sampling"]!["abortedReplies"] = liveOllama.AbortedReplies;
                if (cfg.MaxReplyTokens is not null)
                    summary["sampling"]!["lengthLimitedReplies"] = liveOllama.LengthLimitedReplies;
                summary["sampling"]!["nonConformingVerdicts"] = liveOllama.NonConformingVerdicts;
                if (cfg.VerdictFallback)
                    summary["sampling"]!["fallbackVerdicts"] = liveOllama.FallbackVerdicts;
            }
            summary["sampling"]!["warmUp"] = warmedUp;
        }
        foreach (var key in new[] { "analysisUnit", "nSkills", "nExecutions" })
            summary[key] = analysis[key]?.DeepClone();
        summary["fingerprint"] = cfg.Fingerprint();
        summary["gitHash"] = gitHash ?? GitHash();
        if ((string?)summary["gitHash"] == "unknown")
            log?.WriteLine("[warning] no code commit recorded: not a git checkout; set AIJADE_GIT_COMMIT to the commit this copy was made from");
        foreach (var key in new[] { "conditions", "table", "perCellCI", "diagnostics", "diffInDiff", "effectSizes", "multiplicity", "factorialInteraction", "chiSquare",
                     "chiSquareSelfVerification", "chiSquareExecutionLevel", "mcnemarEnvFeedback", "power", "powerReference" })
            summary[key] = analysis[key]?.DeepClone();
        summary["preregistrationDeviation"] = new JsonArray(Harness.ValidatePreregistration(new RunOptions(backend, cfg.Trials, cfg.Rounds, cfg.Seed, cfg.Tasks, sandbox,
            cfg.PruneThreshold, cfg.PruneMinCalls)).Select(d => (JsonNode?)d)
            .Concat(cfg.Temperature != 0 ? [(JsonNode?)$"temperature: run={JsFormat.Number(cfg.Temperature)} preregistered=0"] : [])
            .Concat(cfg.Inert ? [(JsonNode?)"negative control: inert generator (feedback never reaches generate)"] : []).ToArray());
        if (resuming is not null)
        {
            summary["resumed"] = new JsonObject
            {
                ["replayedSteps"] = recorded!.Count,
                ["replayedGenerations"] = resuming.ReplayedGenerations,
                ["replayedVerifications"] = resuming.ReplayedVerifications,
                ["note"] = "the run was interrupted by an infrastructure timeout; the recorded generations and self-verification replies of the interrupted run were replayed (and checked step by step) before the live backend took over",
            };
            summary["preregistrationDeviation"]!.AsArray().Add($"resumed: steps 0–{recorded.Count - 1} replayed from the interrupted run after an infrastructure timeout");
        }
        summary["degeneracy"] = analysis["degeneracy"]?.DeepClone();
        summary["loopDiagnostics"] = analysis["loopDiagnostics"]?.DeepClone();
        await File.WriteAllTextAsync(Path.Combine(outDir, "summary.json"), JsFormat.Stringify(summary, 2) + "\n", ct).ConfigureAwait(false);
        return (outDir, summary);
    }
}
