using System.Globalization;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Identity;
using Aijade.Memory.Locomo;
using Aijade.Memory.Model;
using Aijade.Research.MemoryEval;
using Aijade.Research.RqC;

// Runs the experiments of the papers on this implementation and writes their artefacts.
//   aijade-experiments memory [--locomo <locomo10.json>] [--out experiments/memory]
//   aijade-experiments growth-pilot [--out experiments/growth-pilot]     (P1 §5.8.1 mechanism-level pilot)
//   aijade-experiments sandbox-isolation [--run <rq-c run dir>]        (P2 §4.1)
//   aijade-experiments differential [--run <rq-c run dir>]             (P2 §7: test-passing candidates vs the reference on perturbed inputs)
//   aijade-experiments identity-a7 [--out experiments/p1/identity-a7.json]   (P1 §5.8.2 positive control)
//   aijade-experiments p2-models [--out experiments/rq-c/p2-models.json]   (P2 §5 model-based analysis of every run)
//   aijade-experiments memory-uncertainty [--locomo <locomo10.json>]    (P4 §5: conversation-clustered intervals of the headline contrasts)
//   aijade-experiments longmemeval [--data <longmemeval_s_cleaned.json>] [--out experiments/memory-longmemeval]   (P4 §5.8 replication)
//   aijade-experiments pool-check [--corpus locomo|longmemeval]   (P4 §4.2: coverage of the 150-candidate pool; the diagnostic on the whole store)
//   aijade-experiments delivery-check [--corpus locomo|longmemeval]   (P4 §5.4: delivered recall with the conflict penalty on and off)
//   aijade-experiments gating-check [--corpus locomo|longmemeval]     (P4 §5.5: gating contrasts with the conflict penalty off)
//   aijade-experiments component-scales --corpus longmemeval          (P4 §5.8: component means and spreads on LongMemEval)
//   aijade-experiments format-precheck --model M [--ollama-base-url U] [--out F]   (P2: verdict-format pre-check for a control model)
// The LoCoMo corpus is third-party data (snap-research/locomo) and is not part of the repository: by default it is read from
// $AIJADE_LOCOMO or ~/.local/share/aijade-data/locomo10.json (tools/data/fetch-corpora.sh fetches and verifies it, and LongMemEval_s).

string? Arg(string name) => args.SkipWhile(a => a != name).Skip(1).FirstOrDefault();
var command = args.FirstOrDefault() ?? "";
var root = FindRoot();

switch (command)
{
    case "sandbox-isolation":
        return SandboxIsolation(Path.GetFullPath(Arg("--run") ?? Path.Combine(root, "experiments", "rq-c", "rq-c-s42-ollama-t30-r5")));
    case "differential":
        return Differential(Path.GetFullPath(Arg("--run") ?? Path.Combine(root, "experiments", "rq-c", "redo", "rq-c-s42-ollama-t30-r5")));
    case "growth-pilot":
        var pilotOut = Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "growth-pilot"));
        Directory.CreateDirectory(pilotOut);
        await Aijade.Growth.Pilot.PilotRunner.RunAsync(1, pilotOut);
        Console.WriteLine($"wrote {pilotOut}");
        return 0;
    case "identity-a7":
        return WriteJson(Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "p1", "identity-a7.json")), IdentityA7());
    case "p2-models":
        return WriteJson(Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "rq-c", "p2-models.json")), P2Models(root));
    case "gating-check" when Arg("--corpus") == "longmemeval":
        return WithLongMemEval(Arg("--data"), GatingCheckReport,
            Path.GetFullPath(Path.Combine(Arg("--out") ?? Path.Combine(root, "experiments", "memory-longmemeval"), "gating-penalty-off.json")));
    case "gating-check":
        return MemoryPart(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")), "gating-penalty-off.json", GatingCheckReport);
    case "format-precheck":
        return await FormatPrecheckCommand(Arg("--model") ?? throw new ArgumentException("--model is required"), Arg("--ollama-base-url") ?? "http://127.0.0.1:11434",
            Arg("--out"), root);
    case "delivery-check" when Arg("--corpus") == "longmemeval":
        return WithLongMemEval(Arg("--data"), DeliveryCheckReport,
            Path.GetFullPath(Path.Combine(Arg("--out") ?? Path.Combine(root, "experiments", "memory-longmemeval"), "delivery-check.json")));
    case "delivery-check":
        return MemoryPart(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")), "delivery-check.json", DeliveryCheckReport);
    case "component-scales" when Arg("--corpus") == "longmemeval":
        return WithLongMemEval(Arg("--data"), ComponentScalesReport,
            Path.GetFullPath(Path.Combine(Arg("--out") ?? Path.Combine(root, "experiments", "memory-longmemeval"), "component-scales.json")));
    case "component-scales":
        return MemoryPart(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")), "component-scales.json", ComponentScalesReport);
    case "metric-definitions":
        return MemoryPart(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")), "metric-definitions.json", MetricDefinitionsReport);
    case "k-dependence":
        return MemoryPart(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")), "k-dependence.json", KDependenceReport);
    case "memory-uncertainty":
        return MemoryPart(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")), "uncertainty.json", UncertaintyReport);
    case "longmemeval":
        return LongMemEvalReplication(Arg("--data") ?? Environment.GetEnvironmentVariable("AIJADE_LONGMEMEVAL")
            ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "aijade-data", "longmemeval", "longmemeval_s_cleaned.json"),
            Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory-longmemeval")));
    case "pool-check" when Arg("--corpus") == "longmemeval":
        return WithLongMemEval(Arg("--data"), corpus => PoolCheckReport(corpus, "LongMemEval_s (cleaned)", LongMemEvalCorpus.Sha256),
            Path.GetFullPath(Path.Combine(Arg("--out") ?? Path.Combine(root, "experiments", "memory-longmemeval"), "pool-check.json")));
    case "pool-check":
        return MemoryPart(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")), "pool-check.json",
            corpus => PoolCheckReport(corpus, null, null));
    case "memory":
        return Memory(Arg("--locomo") ?? DefaultLocomo(), Path.GetFullPath(Arg("--out") ?? Path.Combine(root, "experiments", "memory")));
    default:
        Console.Error.WriteLine("usage: aijade-experiments memory [--locomo PATH] [--out DIR]");
        return 2;
}

// Replays every saved candidate of a run (candidates.jsonl, in step order) in the .NET sandbox twice — with the shared
// argument fixtures the run used, and with fresh arguments per case — and counts verdicts that differ from the recorded ones,
// plus candidates that read the clock or Math.random.
// P2 §7: the distinct test-passing candidates of a run against hidden suites built from perturbed test arguments.
static int Differential(string run)
{
    var trials = File.ReadLines(Path.Combine(run, "trials.jsonl")).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!).ToList();
    var byTask = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
    foreach (var c in File.ReadLines(Path.Combine(run, "candidates.jsonl")).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!))
    {
        if (!c["execOk"]!.GetValue<bool>() || c["code"]?.GetValue<string>() is not { Length: > 0 } code)
            continue;
        var task = trials[c["step"]!.GetValue<int>()]!["taskId"]!.GetValue<string>();
        (byTask.TryGetValue(task, out var set) ? set : byTask[task] = new HashSet<string>(StringComparer.Ordinal)).Add(code);
    }
    var results = Aijade.Research.SkillBench.DifferentialTesting.Run(byTask.ToDictionary(p => p.Key, p => (IReadOnlyCollection<string>)p.Value));
    var withSuite = results.Where(r => r.HiddenCases > 0).ToList();
    var report = new JsonObject
    {
        ["experiment"] = "differential testing: distinct test-passing candidates against the reference solution on perturbed test arguments (inputs on which the reference throws are dropped)",
        ["run"] = Path.GetFileName(run),
        ["tasks"] = results.Count, ["tasksWithHiddenSuite"] = withSuite.Count,
        ["hiddenCases"] = withSuite.Sum(r => r.HiddenCases),
        ["candidates"] = withSuite.Sum(r => r.Candidates), ["disagreeing"] = withSuite.Sum(r => r.Disagreeing),
        ["tasksWithDisagreement"] = withSuite.Count(r => r.Disagreeing > 0),
        ["perTask"] = new JsonArray([.. results.Select(r => (JsonNode)new JsonObject
        {
            ["task"] = r.TaskId, ["hiddenCases"] = r.HiddenCases, ["candidates"] = r.Candidates, ["disagreeing"] = r.Disagreeing,
            ["examples"] = new JsonArray([.. r.Examples.Select(e => (JsonNode)JsonValue.Create(e))]),
        })]),
    };
    File.WriteAllText(Path.Combine(run, "differential.json"), JsFormat.Stringify(report, 2) + "\n");
    Console.WriteLine($"{report["candidates"]} candidates, {report["disagreeing"]} disagree with the reference on {report["hiddenCases"]} hidden cases");
    return 0;
}

static int SandboxIsolation(string run)
{
    var trials = File.ReadLines(Path.Combine(run, "trials.jsonl")).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!).ToList();
    var candidates = File.ReadLines(Path.Combine(run, "candidates.jsonl")).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!).ToList();
    var tasks = Aijade.Research.SkillBench.Bench.Tasks.ToDictionary(t => t.Id);
    var shared = new Aijade.Research.SkillBench.Sandbox();
    var isolated = new Aijade.Research.SkillBench.Sandbox { IsolateArguments = true };
    var clock = new System.Text.RegularExpressions.Regex(@"Math\.random|Date\.now\s*\(|new Date\s*\(\s*\)|performance\.now");
    int same = 0, isolatedDiffers = 0, clockReaders = 0;
    foreach (var c in candidates)
    {
        var step = c["step"]!.GetValue<int>();
        var task = tasks[trials[step]!["taskId"]!.GetValue<string>()];
        var code = c["code"]?.GetValue<string>() ?? "";
        var recorded = c["execOk"]!.GetValue<bool>();
        if (shared.RunTask(code, task).Ok == recorded)
            same++;
        if (isolated.RunTask(code, task).Ok != recorded)
            isolatedDiffers++;
        if (clock.IsMatch(code))
            clockReaders++;
    }
    var report = new JsonObject
    {
        ["experiment"] = "sandbox isolation: saved candidates replayed with shared and with fresh argument fixtures",
        ["run"] = Path.GetFileName(run), ["candidates"] = candidates.Count,
        ["replayedAsRecorded"] = same, ["verdictsDifferWithFreshArguments"] = isolatedDiffers, ["candidatesReadingClockOrRandom"] = clockReaders,
    };
    File.WriteAllText(Path.Combine(run, "sandbox-isolation.json"), JsFormat.Stringify(report, 2) + "\n");
    Console.WriteLine(report.ToJsonString());
    return same == candidates.Count ? 0 : 1;
}

static int WriteJson(string path, JsonObject body)
{
    body["runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription;
    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
    File.WriteAllText(path, JsFormat.Stringify(body, 2) + "\n");
    Console.WriteLine($"wrote {path}");
    return 0;
}

// P1 Appendix A.7: four out-of-bounds identity proposals, each built to reach its pre-registered rejection stage, and one
// legitimate control, under the shipped configuration and under the configuration in which the consent parameter also
// carries a safety bound (the safety check then runs first and the consent stage is unreachable).
static JsonObject IdentityA7()
{
    static IdentityState Near(string key, double v)
    {
        var s = IdentityState.Default;
        s.Constitutional[key] = v;
        return s;
    }
    static Dictionary<IdentityLayer, OrderedDictionary<string, double>> D(IdentityLayer layer, string key, double value) =>
        new() { [layer] = new() { [key] = value } };
    static IdentityEvidence Ev(string id) => new(id, IdentitySource.User, true, "preference", EvidenceTrigger.Deliberate);
    IdentityEvidence[] two = [Ev("e1"), Ev("e2")];
    var cases = new (string Case, string Expected, IdentityState Current, IdentityCandidate Candidate)[]
    {
        ("①", "constraint", IdentityState.Default, new("c", IdentitySource.User, two, D(IdentityLayer.Character, "verbosity", 0.6))),
        ("②", "constraint", IdentityState.Default, new("c", IdentitySource.User, [Ev("e1"), Ev("e1")], D(IdentityLayer.Character, "verbosity", 0.1))),
        ("③", "safety", Near("harmThreshold", 0.9), new("c", IdentitySource.User, two, D(IdentityLayer.Constitutional, "harmThreshold", 0.2), ExplicitUpgrade: true)),
        ("④", "consent", Near("userConsent", 0.9), new("c", IdentitySource.User, two, D(IdentityLayer.Constitutional, "userConsent", 0.2), ExplicitUpgrade: true)),
        ("legit", "ok", IdentityState.Default, new("c", IdentitySource.User, two, D(IdentityLayer.Character, "verbosity", 0.1))),
    };
    JsonArray Run(CdiConfig cfg) => [.. cases.Select(c =>
    {
        var r = Cdi.Solve(c.Current, c.Candidate, cfg);
        var got = r.Ok ? "ok" : r.Stage!.Value.ToString().ToLowerInvariant();
        return (JsonNode)new JsonObject { ["case"] = c.Case, ["expected"] = c.Expected, ["got"] = got, ["stageMatches"] = got == c.Expected };
    })];
    return new JsonObject
    {
        ["experiment"] = "P1 Appendix A.7 positive control (CDI rejection stages)",
        ["shipped"] = Run(CdiConfig.Default),
        ["consentAlsoSafetyBound"] = Run(CdiConfig.ConsentAlsoSafetyBound),
    };
}

// The analysis P2 §5 describes (skill-level log-odds interaction, logistic regression with cluster-robust SEs, mixed-effects
// logistic regression with a task random intercept, clustered McNemar, diagnostics) for every finished RQ-C run, beside the
// cell-count "interaction" the harness summary reports.
static JsonObject P2Models(string root)
{
    var rqc = Path.Combine(root, "experiments", "rq-c");
    var runs = new (string Name, string Dir)[]
    {
        ("main (7B)", Path.Combine(rqc, "redo", "rq-c-s42-ollama-t30-r5")),
        ("negative control (7B, inert)", Path.Combine(rqc, "redo", "rq-c-s42-ollama-t30-r5-INERT")),
        ("positive control (mock)", Path.Combine(rqc, "rq-c-s42-mock-t30-r5")),
        ("second model (1.5B)", Path.Combine(rqc, "rq-c-s42-ollama-t30-r5")),
        ("1.5B, T = 0.4 (exploratory)", Path.Combine(rqc, "sweep-1.5b", "rq-c-s42-ollama-t30-r5-T0.4")),
        ("1.5B, T = 0.8 (exploratory)", Path.Combine(rqc, "sweep-1.5b", "rq-c-s42-ollama-t30-r5-T0.8")),
        ("second family (llama3.1:8b)", Path.Combine(rqc, "family-gpu", "rq-c-s42-ollama-t30-r5")),
        ("second family, first attempt (llava-phi3)", Path.Combine(rqc, "family", "rq-c-s42-ollama-t30-r5")),
        ("prompt template A (7B, GPU host)", Path.Combine(rqc, "template-gpu", "A", "rq-c-s42-ollama-t30-r5")),
        ("prompt template B (7B, GPU host)", Path.Combine(rqc, "template-gpu", "B", "rq-c-s42-ollama-t30-r5")),
    };
    var result = new JsonObject { ["experiment"] = "P2 model-based analysis of the RQ-C runs" };
    foreach (var (name, dir) in runs)
    {
        var summaryPath = Path.Combine(dir, "summary.json");
        if (!File.Exists(summaryPath))
            continue;
        var summary = JsonNode.Parse(File.ReadAllText(summaryPath))!;
        var seed = (uint)summary["config"]!["seed"]!.GetValue<int>();
        var steps = StepRecord.ReadJsonl(Path.Combine(dir, "trials.jsonl"));
        var skills = RqcAnalysis.ReplaySkills(steps, new RqcConfig(seed));
        var models = RqcModels.Analyze(skills);
        models["slotLevel"] = RqcModels.AnalyzeSlots(skills);
        models["clusteredMcNemar"] = RqcModels.ClusteredMcNemar(skills);
        models["diagnostics"] = RqcModels.Diagnostics(skills);
        models["harnessInteraction"] = new JsonObject
        {
            ["what"] = "log(S00·S11 / (S01·S10)) over each cell's count of successful executions",
            ["estimate"] = summary["factorialInteraction"]?["estimate"]?.DeepClone(),
            ["p"] = summary["factorialInteraction"]?["p"]?.DeepClone(),
        };
        var candidatesPath = Path.Combine(dir, "candidates.jsonl");
        if (File.Exists(candidatesPath))
        {
            var codes = File.ReadLines(candidatesPath).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!)
                .OrderBy(c => c["step"]!.GetValue<int>()).Select(c => c["code"]?.GetValue<string>()).ToList();
            models["loop"] = RqcModels.ChangedCodeRecoveries(steps, codes);
            // Verifier replies that do not begin with PASS or FAIL are FAIL verdicts under the pre-registered rule. When a run
            // has any, the same diagnostics are recomputed with their last explicit "verdict: PASS|FAIL" read from the recorded
            // reply (exploratory; a reply truncated before its verdict, or without one, stays a FAIL).
            var replies = File.ReadLines(candidatesPath).Where(l => l.Length > 0).Select(l => JsonNode.Parse(l)!)
                .OrderBy(c => c["step"]!.GetValue<int>()).Select(c => c["selfReply"]?.GetValue<string>() ?? c["selfRationale"]?.GetValue<string>()).ToList();
            if (replies.Count == steps.Count)
            {
                int judged = 0, nonConforming = 0, readPass = 0, readFail = 0;
                var reread = steps.Select((st, i) =>
                {
                    if (st.SelfVerdict is null || replies[i] is not { } reply)
                        return st;
                    judged++;
                    var pass = OllamaBackend.ReadVerdict(reply, fallback: true, out var conforming, out var byFallback);
                    if (conforming)
                        return st;
                    nonConforming++;
                    if (byFallback)
                        _ = pass ? readPass++ : readFail++;
                    return st with { SelfVerdict = pass ? "pass" : "fail" };
                }).ToList();
                if (nonConforming > 0)
                {
                    models["verdictFallback"] = new JsonObject
                    {
                        ["what"] = "exploratory: non-conforming verifier replies read by their last explicit verdict; unreadable ones stay FAIL",
                        ["judged"] = judged, ["nonConforming"] = nonConforming, ["readPass"] = readPass, ["readFail"] = readFail,
                        ["unreadable"] = nonConforming - readPass - readFail,
                        ["diagnostics"] = RqcModels.Diagnostics(RqcAnalysis.ReplaySkills(reread, new RqcConfig(seed))),
                    };
                }
            }
        }
        models["run"] = Path.GetRelativePath(root, dir);
        result[name] = models;
    }
    return result;
}

static JsonObject UncertaintyReport(IReadOnlyList<LocomoConversation> corpus) => new()
{
    ["experiment"] = "uncertainty of the headline contrasts of P4 §5, the conversation as the unit of dependence: conversation bootstrap (10,000 resamples, percentile 95%) and exact sign-flip randomisation over the paired per-conversation differences",
    ["k"] = MemoryUncertainty.K,
    ["contrasts"] = new JsonArray([.. MemoryUncertainty.Run(corpus).Select(c => (JsonNode)new JsonObject
    {
        ["key"] = c.Key, ["caliber"] = c.Caliber, ["a"] = c.A, ["b"] = c.B, ["difference"] = c.Difference,
        ["bootstrap95"] = new JsonArray(c.BootstrapLo, c.BootstrapHi), ["signFlipP"] = c.SignFlipP,
        ["conversationsPositive"] = c.ConversationsPositive, ["conversationsNegative"] = c.ConversationsNegative, ["conversations"] = c.Conversations,
    })]),
};

static JsonObject MetricDefinitionsReport(IReadOnlyList<LocomoConversation> corpus)
{
    static JsonObject Ks(IReadOnlyDictionary<int, double> x) => new(x.Select(p => KeyValuePair.Create(p.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)p.Value)));
    return new JsonObject
    {
        ["experiment"] = "two definition defects of recall@K: aggregation caliber (macro vs micro) and duplicate fact copies over kept fractions q, with and without retrieval-time content dedupe",
        ["aggregationCaliber"] = new JsonArray([.. MetricDefinitions.AggregationCaliber(corpus).Select(c => (JsonNode)new JsonObject
        {
            ["scoreMode"] = WireName.Of(c.Mode), ["macro"] = Ks(c.Macro), ["micro"] = Ks(c.Micro),
        })]),
        ["duplication"] = new JsonArray([.. MetricDefinitions.DuplicationConfusion(corpus).Select(a => (JsonNode)new JsonObject
        {
            ["salience"] = a.Salience, ["q"] = a.Q, ["facts"] = a.Facts, ["dedupe"] = a.Dedupe, ["recall"] = Ks(a.Recall),
            ["evidenceSurvival"] = a.EvidenceSurvival, ["distinctEpisodes"] = a.Distinct, ["poolSize"] = a.PoolSize, ["effectiveTop8"] = a.EffectiveTop8,
        })]),
    };
}

static JsonObject ComponentScalesReport(IReadOnlyList<LocomoConversation> corpus)
{
    var r = RetrievalAblation.ComponentScales(corpus);
    static JsonObject Obj(IReadOnlyDictionary<string, double> x) => new(x.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)p.Value)));
    return new JsonObject
    {
        ["experiment"] = "component scales: mean saturated score components of the gold evidence, the additive top 8 and the pool (no gating)",
        ["questions"] = r.Questions, ["gold"] = Obj(r.Gold), ["additiveTop8"] = Obj(r.AdditiveTop8), ["pool"] = Obj(r.Pool),
        ["poolSd"] = r.PoolSd is null ? null : Obj(r.PoolSd),
    };
}

static JsonObject KDependenceReport(IReadOnlyList<LocomoConversation> corpus)
{
    var report = new JsonObject
    {
        ["experiment"] = "K-dependence: top-k from a top-k call vs the first k of a top-8 call; recall with and without the retrieval floor (no gating; micro over questions)",
    };
    foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized, RetrievalScoreMode.Rrf })
    {
        var d = RetrievalAblation.KDependence(corpus, mode);
        static JsonObject ByK(IReadOnlyDictionary<int, double> x) => new(x.Select(p => KeyValuePair.Create(p.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)p.Value)));
        report[WireName.Of(mode)] = new JsonObject
        {
            ["questions"] = d.Questions, ["orderDiffers"] = ByK(d.OrderDiffers), ["recallDirect"] = ByK(d.RecallDirect),
            ["recallFromTop8"] = ByK(d.RecallFromTop8), ["recallRankOnly"] = ByK(d.RecallRankOnly),
            ["retrievalFloor"] = d.FloorValue, ["maxTop8Score"] = d.MaxScore, ["medianTop8Score"] = d.MedianTop8Score,
        };
    }
    return report;
}

// P4 §5.8: the scorer diagnosis and the gating contrasts replicated on LongMemEval (one haystack per question).
static int LongMemEvalReplication(string data, string outDir)
{
    if (!File.Exists(data))
    {
        Console.Error.WriteLine($"LongMemEval not found at {data}; run tools/data/fetch-corpora.sh longmemeval or pass --data");
        return 2;
    }
    var sha = LocomoCorpus.FileSha256(data);
    if (sha != LongMemEvalCorpus.Sha256)
    {
        Console.Error.WriteLine($"LongMemEval checksum mismatch: {sha}");
        return 2;
    }
    var clock = System.Diagnostics.Stopwatch.StartNew();
    var corpus = LongMemEvalCorpus.Load(data);
    var weights = WeightAblation.Run(corpus);
    var contrasts = MemoryUncertainty.Run(corpus);
    static JsonObject Ks(IReadOnlyDictionary<int, double> x) => new(x.Select(p => KeyValuePair.Create(p.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)p.Value)));
    var report = new JsonObject
    {
        ["experiment"] = "replication of the scorer diagnosis (recency bias, weight ablation) and the gating contrasts on LongMemEval_s; each question has its own haystack, so the question is the unit of resampling",
        ["provenance"] = new JsonObject
        {
            ["corpus"] = "LongMemEval_s (cleaned)", ["corpusSha256"] = sha, ["questions"] = corpus.Count,
            ["episodes"] = corpus.Sum(c => c.Episodes.Count), ["runtimeSeconds"] = Math.Round(clock.Elapsed.TotalSeconds),
            ["generatedAt"] = DateTimeOffset.UtcNow.ToString("o", CultureInfo.InvariantCulture),
        },
        ["recencyBias"] = new JsonObject
        {
            ["meanNewerInTopK"] = weights.RecencyBias.MeanNewerInTopK, ["baselineIfUnbiased"] = weights.RecencyBias.BaselineIfUnbiased,
            ["meanSlotAgePercentile"] = weights.RecencyBias.MeanSlotAgePercentile, ["scanned"] = weights.RecencyBias.Scanned,
        },
        ["recallByWeights"] = new JsonObject([.. weights.RecallByWeights.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)Ks(p.Value)))]),
        ["contrasts"] = new JsonArray([.. contrasts.Select(c => (JsonNode)new JsonObject
        {
            ["key"] = c.Key, ["caliber"] = c.Caliber, ["a"] = c.A, ["b"] = c.B, ["difference"] = c.Difference,
            ["bootstrap95"] = new JsonArray(c.BootstrapLo, c.BootstrapHi), ["signFlipP"] = c.SignFlipP,
            ["unitsPositive"] = c.ConversationsPositive, ["unitsNegative"] = c.ConversationsNegative, ["units"] = c.Conversations,
        })]),
    };
    Directory.CreateDirectory(outDir);
    File.WriteAllText(Path.Combine(outDir, "replication.json"), JsFormat.Stringify(report, 2) + "\n");
    Console.WriteLine($"wrote {Path.Combine(outDir, "replication.json")} ({corpus.Count} questions, {clock.Elapsed.TotalMinutes:0.0} min)");
    return 0;
}

// The diagnostic track's pool is the store's top 150 under its own (standardised) score. One retrieval per question gives
// the published variant (that pool, floor applied), the pool's coverage, and the diagnostic re-run on the whole store.
static JsonObject PoolCheckReport(IReadOnlyList<LocomoConversation> corpus, string? corpusName, string? sha)
{
    var clock = System.Diagnostics.Stopwatch.StartNew();
    // one run per conversation (in parallel), combined exactly; the per-conversation results also give the paired contrasts
    var perConv = WeightAblation.RunVariantsPerConversation(corpus, null, [(WeightAblation.RerankPool, true), (WeightAblation.RerankPool, false), (int.MaxValue, false)]);
    var results = Enumerable.Range(0, 3).Select(v => WeightAblation.Combine([.. perConv.Select(p => p[v])])).ToList();
    var questions = perConv.Select(p => (double)p[0].Questions).ToArray();
    double[] Hits(int v, string arm) => [.. perConv.Select(p => p[v].RecallByWeights[arm][MemoryUncertainty.K] * p[v].Questions)];
    static JsonObject Contrast(PairedContrast c) => new()
    {
        ["key"] = c.Key, ["caliber"] = c.Caliber, ["a"] = c.A, ["b"] = c.B, ["difference"] = c.Difference,
        ["bootstrap95"] = new JsonArray(c.BootstrapLo, c.BootstrapHi), ["signFlipP"] = c.SignFlipP,
        ["unitsPositive"] = c.ConversationsPositive, ["unitsNegative"] = c.ConversationsNegative, ["units"] = c.Conversations,
    };
    static JsonObject Ks(IReadOnlyDictionary<int, double> x) => new(x.Select(p => KeyValuePair.Create(p.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)p.Value)));
    static JsonObject Variant(string what, WeightAblationResult r) => new()
    {
        ["what"] = what,
        ["questions"] = r.Questions,
        ["poolCoverage"] = r.PoolCoverage,
        ["recencyBias"] = new JsonObject { ["meanNewerInTopK"] = r.RecencyBias.MeanNewerInTopK, ["baselineIfUnbiased"] = r.RecencyBias.BaselineIfUnbiased, ["meanSlotAgePercentile"] = r.RecencyBias.MeanSlotAgePercentile },
        ["recallByWeights"] = new JsonObject([.. r.RecallByWeights.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)Ks(p.Value)))]),
    };
    var report = new JsonObject
    {
        ["experiment"] = "coverage of the diagnostic track's 150-candidate pool (chosen by the store's standardised score) and the diagnostic on the whole store, judged on rank alone (micro)",
        ["published"] = Variant("top 150 under the store score, retrieval floor applied (the published diagnostic track)", results[0]),
        ["pool150RankOnly"] = Variant("top 150 under the store score, rank alone", results[1]),
        ["wholeStore"] = Variant("every candidate, rank alone", results[2]),
        ["contrasts"] = new JsonArray(
            Contrast(MemoryUncertainty.Micro("weights (150-candidate pool, floor): sim-only vs current", Hits(0, "sim-only"), Hits(0, "current"), questions, 10000, 0x5EED_2026)),
            Contrast(MemoryUncertainty.Micro("weights (whole store, rank alone): sim-only vs current", Hits(2, "sim-only"), Hits(2, "current"), questions, 10000, 0x5EED_2026))),
        ["runtimeSeconds"] = Math.Round(clock.Elapsed.TotalSeconds),
    };
    if (corpusName is not null)
        report["provenance"] = new JsonObject { ["corpus"] = corpusName, ["corpusSha256"] = sha, ["questions"] = corpus.Count, ["generatedAt"] = DateTimeOffset.UtcNow.ToString("o", CultureInfo.InvariantCulture) };
    return report;
}

// The gating contrasts of P4 §5.5 again with the conflict penalty switched off (1.0); same units, bootstrap and test.
static JsonObject GatingCheckReport(IReadOnlyList<LocomoConversation> corpus) => new()
{
    ["experiment"] = "gating ON - OFF at K = 8 (macro) under each score mode and salience source, with the conflict penalty switched off (1.0); unit bootstrap and sign-flip test as in uncertainty.json",
    ["conflictPenalty"] = 1.0,
    ["contrasts"] = new JsonArray([.. MemoryUncertainty.Run(corpus, conflictPenalty: 1.0, includeWeights: false).Select(c => (JsonNode)new JsonObject
    {
        ["key"] = c.Key, ["caliber"] = c.Caliber, ["a"] = c.A, ["b"] = c.B, ["difference"] = c.Difference,
        ["bootstrap95"] = new JsonArray(c.BootstrapLo, c.BootstrapHi), ["signFlipP"] = c.SignFlipP,
        ["unitsPositive"] = c.ConversationsPositive, ["unitsNegative"] = c.ConversationsNegative, ["units"] = c.Conversations,
    })]),
};

// The verdict-format pre-check of a candidate control model, with the run's own sampling (seed derived from the master seed 42,
// temperature 0, warm-up, replies capped at 4096 tokens).
static async Task<int> FormatPrecheckCommand(string model, string baseUrl, string? outArg, string root)
{
    using var http = new HttpClient { Timeout = System.Threading.Timeout.InfiniteTimeSpan };
    var sampling = new RqcCliConfig { Backend = RqcBackendKind.Ollama, Model = model };
    var numCtx = int.TryParse(Environment.GetEnvironmentVariable("AIJADE_NUM_CTX"), out var c) ? c : (int?)null;
    var backend = new OllamaBackend(http, model, baseUrl, 0, sampling.SamplingSeed, TimeSpan.FromMinutes(30), 4096, numCtx: numCtx);
    var items = await FormatPrecheck.RunAsync(backend);
    var report = FormatPrecheck.Report(items);
    report["model"] = model;
    report["modelDigest"] = await OllamaBackend.DigestAsync(http, baseUrl, model);
    report["ollamaVersion"] = await OllamaBackend.VersionAsync(http, baseUrl);
    report["baseUrl"] = baseUrl;
    report["numCtx"] = numCtx;
    report["generatedAt"] = DateTimeOffset.UtcNow.ToString("o", CultureInfo.InvariantCulture);
    var safe = string.Concat(model.Select(c => char.IsLetterOrDigit(c) || c is '.' or '-' ? c : '_'));
    var outFile = Path.GetFullPath(outArg ?? Path.Combine(root, "experiments", "rq-c", "format-precheck", $"{safe}.json"));
    Directory.CreateDirectory(Path.GetDirectoryName(outFile)!);
    File.WriteAllText(outFile, JsFormat.Stringify(report, 2) + "\n");
    Console.WriteLine($"{model}: {report["conforming"]}/{report["items"]} conforming, pass = {report["pass"]} ({outFile})");
    return 0;
}

static JsonObject DeliveryCheckReport(IReadOnlyList<LocomoConversation> corpus) => new()
{
    ["experiment"] = "delivery track without gating: recall@8 (macro) per score mode with the conflict penalty at its default and switched off (1.0); share of top-8 slots penalised; share of questions with a penalised gold item in the scanned head (8 additive, 150 standardised)",
    ["rows"] = new JsonArray([.. RetrievalAblation.DeliveryCheck(corpus).Select(r => (JsonNode)new JsonObject
    {
        ["mode"] = WireName.Of(r.Mode), ["conflictPenalty"] = r.ConflictPenalty, ["recall8Macro"] = r.MacroRecall8,
        ["penalizedShareOfTop8"] = r.PenalizedShareOfTop8, ["goldPenalizedShare"] = r.GoldPenalizedShare,
    })]),
};

static int WithLongMemEval(string? dataArg, Func<IReadOnlyList<LocomoConversation>, JsonObject> run, string outFile)
{
    var data = dataArg ?? Environment.GetEnvironmentVariable("AIJADE_LONGMEMEVAL")
        ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "aijade-data", "longmemeval", "longmemeval_s_cleaned.json");
    if (!File.Exists(data) || LocomoCorpus.FileSha256(data) != LongMemEvalCorpus.Sha256)
    {
        Console.Error.WriteLine($"LongMemEval missing or checksum mismatch at {data}; run tools/data/fetch-corpora.sh longmemeval or pass --data");
        return 2;
    }
    var corpus = LongMemEvalCorpus.Load(data);
    var report = run(corpus);
    report["provenance"] ??= new JsonObject
    {
        ["corpus"] = "LongMemEval_s (cleaned)", ["corpusSha256"] = LongMemEvalCorpus.Sha256, ["questions"] = corpus.Count,
        ["runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription, ["generatedAt"] = DateTimeOffset.UtcNow.ToString("o", CultureInfo.InvariantCulture),
    };
    Directory.CreateDirectory(Path.GetDirectoryName(outFile)!);
    File.WriteAllText(outFile, JsFormat.Stringify(report, 2) + "\n");
    Console.WriteLine($"wrote {outFile}");
    return 0;
}

static string DefaultLocomo() => Environment.GetEnvironmentVariable("AIJADE_LOCOMO")
    ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "aijade-data", "locomo10.json");

// One part of the memory experiments, with the same corpus checks and provenance block as the full run.
static int MemoryPart(string locomo, string outDir, string name, Func<IReadOnlyList<LocomoConversation>, JsonObject> run) =>
    WithCorpus(locomo, outDir, (corpus, write) => write(name, run(corpus)));

static int Memory(string locomo, string outDir) => WithCorpus(locomo, outDir, (corpus, write) => MemoryAll(corpus, write));

static int WithCorpus(string locomo, string outDir, Action<IReadOnlyList<LocomoConversation>, Action<string, JsonObject>> body)
{
    if (!File.Exists(locomo))
    {
        Console.Error.WriteLine($"LoCoMo corpus not found at {locomo}; run tools/data/fetch-corpora.sh or pass --locomo");
        return 2;
    }
    var sha = LocomoCorpus.FileSha256(locomo);
    if (sha != LocomoCorpus.Sha256)
    {
        Console.Error.WriteLine($"LoCoMo corpus fingerprint {sha} differs from the expected {LocomoCorpus.Sha256}");
        return 2;
    }
    var corpus = LocomoCorpus.Load(locomo);
    Directory.CreateDirectory(outDir);
    var provenance = new JsonObject
    {
        ["corpus"] = "LoCoMo (snap-research/locomo, data/locomo10.json)", ["corpusSha256"] = sha, ["conversations"] = corpus.Count,
        ["runtime"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription, ["generatedAt"] = DateTimeOffset.UtcNow.ToString("o", CultureInfo.InvariantCulture),
    };
    void Write(string name, JsonObject body)
    {
        body["provenance"] = provenance.DeepClone();
        File.WriteAllText(Path.Combine(outDir, name), JsFormat.Stringify(body, 2) + "\n");
        Console.WriteLine($"wrote {Path.Combine(outDir, name)}");
    }
    body(corpus, Write);
    return 0;
}

static void MemoryAll(IReadOnlyList<LocomoConversation> corpus, Action<string, JsonObject> Write)
{
    var weights = WeightAblation.Run(corpus);
    Write("weight-ablation.json", new JsonObject
    {
        ["experiment"] = "weight ablation: the same 150-candidate pool re-ranked under component weights (no gating)",
        ["questions"] = weights.Questions,
        ["recallByWeights"] = new JsonObject(weights.RecallByWeights.Select(p => KeyValuePair.Create(p.Key,
            (JsonNode?)new JsonObject(p.Value.Select(k => KeyValuePair.Create(k.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)k.Value)))))),
        ["recencyBias"] = new JsonObject
        {
            ["scanned"] = weights.RecencyBias.Scanned, ["evidenceMissing"] = weights.RecencyBias.EvidenceMissing,
            ["meanNewerInTopK"] = weights.RecencyBias.MeanNewerInTopK, ["baselineIfUnbiased"] = weights.RecencyBias.BaselineIfUnbiased,
            ["meanSlotAgePercentile"] = weights.RecencyBias.MeanSlotAgePercentile,
        },
    });

    var arms = RetrievalAblation.CombinationAblation(corpus);
    Write("combination-ablation.json", new JsonObject
    {
        ["experiment"] = "score combination: additive vs z-score standardisation vs RRF (k = 60) on the same pool; floor judged on the store score",
        ["questions"] = arms.Questions,
        ["arms"] = new JsonArray([.. arms.Arms.Select(a => (JsonNode)new JsonObject
        {
            ["key"] = a.Key, ["combine"] = a.Combine, ["primary"] = a.Primary, ["mrr"] = a.Mrr,
            ["recall"] = new JsonObject(a.Recall.Select(k => KeyValuePair.Create(k.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)k.Value))),
            ["ndcg"] = new JsonObject(a.Ndcg.Select(k => KeyValuePair.Create(k.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)k.Value))),
        })]),
    });

    Write("component-scales.json", ComponentScalesReport(corpus));
    Write("k-dependence.json", KDependenceReport(corpus));

    var gating = new JsonObject();
    foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized, RetrievalScoreMode.Rrf })
    {
        var g = RetrievalAblation.GatingInterference(corpus, mode);
        static JsonObject Pairs(IReadOnlyDictionary<int, (double On, double Off)> d) =>
            new(d.Select(p => KeyValuePair.Create(p.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)new JsonObject { ["on"] = p.Value.On, ["off"] = p.Value.Off })));
        gating[WireName.Of(mode)] = new JsonObject
        {
            ["recall"] = Pairs(g.Recall), ["distractorLoad"] = Pairs(g.DistractorLoad),
            ["recallCorrectedWeights"] = Pairs(g.RecallCorrected), ["distractorLoadCorrectedWeights"] = Pairs(g.DistractorLoadCorrected),
        };
    }
    Write("gating-interference.json", new JsonObject
    {
        ["experiment"] = "salience gating ON (DEFAULT) vs OFF (NONE): recall@K and distractor load, per retrieval score mode",
        ["byScoreMode"] = gating,
    });

    static JsonObject KsJson(IReadOnlyDictionary<int, double> d) =>
        new(d.Select(p => KeyValuePair.Create(p.Key.ToString(CultureInfo.InvariantCulture), (JsonNode?)p.Value)));
    var salience = new JsonObject();
    foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized })
    {
        var r = SalienceDiagnostics.Run(corpus, mode);
        salience[WireName.Of(mode)] = new JsonObject
        {
            ["auc"] = new JsonObject(r.Auc.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)p.Value))),
            ["conditions"] = new JsonObject(r.Conditions.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)new JsonObject
            {
                ["recall"] = KsJson(p.Value.Recall), ["hitScoreMean"] = p.Value.HitScoreMean, ["evidenceSurvival"] = p.Value.EvidenceSurvival,
                ["prunedTotal"] = p.Value.PrunedTotal, ["poolSize"] = p.Value.PoolSize,
            }))),
        };
    }
    Write("salience-sources.json", new JsonObject
    {
        ["experiment"] = "salience source (oracle / predicted / shuffled) × gating ON/OFF, plus ON without selective consolidation; macro recall@K",
        ["byScoreMode"] = salience,
    });

    var leak = SalienceLeakageAudit.Run(corpus);
    Write("salience-leakage-audit.json", new JsonObject
    {
        ["experiment"] = "nested cross-validation audit of the learned salience model: standardisation and feature-selection leakage",
        ["rows"] = leak.Rows, ["positives"] = leak.Positives, ["features"] = leak.Features,
        ["pooledAuc"] = new JsonObject { ["locvOriginal"] = leak.LocvOriginal, ["locvTrainStd"] = leak.LocvTrainStd, ["nestedTrain"] = leak.Nested },
        ["leak"] = new JsonObject { ["standardization"] = leak.LocvOriginal - leak.LocvTrainStd, ["featureSelection"] = leak.LocvTrainStd - leak.Nested },
        ["folds"] = new JsonArray([.. leak.Folds.Select(f => (JsonNode)new JsonObject
        {
            ["fold"] = f.Fold, ["auc"] = f.Auc, ["selected"] = new JsonArray([.. f.Selected.Select(n => (JsonNode)n)]),
        })]),
    });

    Write("metric-definitions.json", MetricDefinitionsReport(corpus));
}

static string FindRoot()
{
    var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "Aijade.slnx")))
        dir = dir.Parent;
    return dir?.FullName ?? throw new InvalidOperationException("run inside the AIJADE-next checkout");
}
