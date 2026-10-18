// Inline fixture arrays read better than hoisted fields in these one-shot golden scenarios.
#pragma warning disable CA1861
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Growth;
using Aijade.Growth.Adapters;
using Aijade.Growth.Services;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Tests;

/// <summary>
/// The growth services replayed on the recorded scenario (frozen clock, fixed random value, Asia/Seoul) must produce the
/// same records, ids, signatures and errors as the golden data.
/// </summary>
public class GrowthServicesTests
{
    private const double T0 = 1_700_000_000_000;
    private const string A = "agent-1";
    private const string S = "scope-1";

    private static readonly JsonNode Golden = JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "growth", "services.json")))!;

    private static readonly TimeZoneInfo Seoul = TimeZoneInfo.FindSystemTimeZoneById("Asia/Seoul");

    private sealed class MutableTime(Func<double> now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => DateTimeOffset.FromUnixTimeMilliseconds((long)now());
    }

    private sealed class RecordingLlm(ILlmPort inner) : ILlmPort
    {
        public List<string> Prompts { get; } = [];

        public Task<string> CompleteAsync(string prompt, CancellationToken cancellationToken = default)
        {
            Prompts.Add(prompt);
            return inner.CompleteAsync(prompt, cancellationToken);
        }
    }

    private static JsonNode? J(object? value) => value is null ? null : JsonSerializer.SerializeToNode(value, value.GetType(), GrowthJson.Options);

    private static JsonArray Arr(IEnumerable<object?> items) => new([.. items.Select(J)]);

    private static async Task<string> ErrorOf(Func<Task> action)
    {
        try
        {
            await action();
        }
        catch (InvalidOperationException e)
        {
            return e.Message;
        }
        return "";
    }

    private static ShareUtility U(double r, double i) => new(r, r, r, r, r, i, i, i);

    [Fact]
    public async Task Services_match_the_original_scenario()
    {
        var ct = TestContext.Current.CancellationToken;
        var clock = T0;
        var ids = new GrowthIds(() => clock, () => 0.5);
        var output = new JsonObject();

        output["util"] = new JsonObject
        {
            ["fnv"] = Arr(new[] { "", "a", "hello world", "漢字🙂" }.Select(GrowthUtil.Fnv1a)),
            ["content"] = GrowthUtil.ContentHashOf("some content"),
            ["today"] = Arr(new[] { T0, T0 + (13 * 3600_000), T0 + (17 * 3600_000), 0 }.Select(t => GrowthUtil.TodayIso(t, Seoul))),
            ["quiet"] = Arr(new[] { T0, T0 - 3600_000, T0 + (3600_000 * 10), T0 + (3600_000 * 16), T0 + (3600_000 * 15) }.Select(t => (object)SharingPolicy.IsQuietHour(t, Seoul))),
            ["share"] = SharingPolicy.ComputeShareScore(GrowthLoop.DefaultShareUtility),
            ["ids"] = Arr([ids.NewId("x"), ids.NewId("yy")]),
            ["stages"] = Arr(new[] { "active", "paused", "needs_consent", "contradicted", "failed", "abandoned", "satisfied" }
                .Select(s => QuestPlanner.QuestStatusToStage(s) is { } st ? JsonNamingPolicy.SnakeCaseUpper.ConvertName(st.ToString()) : null)),
            ["signIm"] = new InMemorySigning().Sign(SignPayload()),
            ["signCrypto"] = new CryptoSigningAdapter("k").Sign(SignPayload()),
        };

        var storage = new InMemoryStorage();
        var sched = new FixedScheduler(T0);
        var ports = new GrowthPorts(storage, sched, Ids: ids, TimeZone: Seoul);
        var comps = new InterestComponents(0.6, 0.5, 0.7, 0.5, 0.6, 0.5, 0.2, 0.1, 0.1);

        // interest
        var interest = new InterestService(ports, A, S);
        var t1 = await interest.CreateThreadAsync(new("Birds", ["e1"], comps, 0.8, 0.3, 0.5), ct);
        var t2 = await interest.CreateThreadAsync(new("Rust", ["e2"], comps with { Novelty = 1, Risk = 0.5 }, 0.4, 0.9, 0.2, MotivatingQuestions: ["why"], Progress: 0.3), ct);
        var t3 = await interest.CreateThreadAsync(new("birds ", ["e3"], comps with { Cost = 0.9 }, 0.2, 0.2, 0.9), ct);
        sched.Time = T0 + 1000;
        var adv = new List<object?>
        {
            await interest.AdvanceAsync(t1.Id, InterestSignal.Probe, ct), await interest.AdvanceAsync(t1.Id, InterestSignal.Incubate, ct),
            await interest.AdvanceAsync(t3.Id, InterestSignal.Abandon, ct), await interest.AdvanceAsync(t3.Id, InterestSignal.Probe, ct),
            await interest.AdvanceAsync("nope", InterestSignal.Probe, ct),
        };
        var sel = await interest.SelectActiveAsync(2, cancellationToken: ct);
        var sel2 = await interest.SelectActiveAsync(3, new PortfolioOptions(3, ForbiddenSubjects: ["rust"]), ct);
        var threadErr = await ErrorOf(() => interest.CreateThreadAsync(new(" ", ["e"], comps, 0, 0, 0), ct));
        output["interest"] = new JsonObject
        {
            ["t1"] = J(t1), ["t2"] = J(t2), ["t3"] = J(t3), ["adv"] = Arr(adv), ["sel"] = J(sel), ["sel2"] = J(sel2),
            ["list"] = Arr((await interest.ListAsync(ct)).Select(t => t.Id)), ["threadErr"] = threadErr,
        };

        // quests
        var planner = new QuestPlanner(ports, A, S);
        var q1 = await planner.CreateQuestAsync(new(t1.Id, "Why do birds migrate?", "seasonal movement", 0.6, QuestionType.Academic, "exp-1"), ct);
        var q2 = await planner.CreateQuestAsync(new(t2.Id, "Rust 2027?", "edition", 0.3, QuestionType.TimelyFact, "exp-2", PriorBeliefs: ["p"], PrivacyClass: "private", StopConditions: ["x"]), ct);
        var qt = new List<object?>
        {
            await planner.TransitionAsync(q1.Id, QuestEvent.Pause, ct), await planner.TransitionAsync(q1.Id, QuestEvent.Resume, ct),
            await planner.TransitionAsync(q1.Id, QuestEvent.NeedConsent, ct), await planner.TransitionAsync(q2.Id, QuestEvent.Fail, ct),
            await planner.TransitionAsync(q2.Id, QuestEvent.Advance, ct), await planner.SatisfyAsync(q1.Id, ct),
            await planner.TransitionAsync(q1.Id, QuestEvent.Advance, ct), await planner.SatisfyAsync("none", ct),
        };
        var questErr = await ErrorOf(() => planner.CreateQuestAsync(new(t1.Id, "q", "o", 2, QuestionType.Everyday, "e"), ct));
        output["quests"] = new JsonObject { ["q1"] = J(q1), ["q2"] = J(q2), ["qt"] = Arr(qt), ["questErr"] = questErr };

        // acquire
        RawHit[] seed =
        [
            new("https://a.example/birds", "paper", "Birds migrate south in winter", 1),
            new("https://b.example/birds-repost", "news", "Birds migrate south in winter", 2),
            new("https://c.example/x", "model", "A model summary about birds", 3),
            new("https://d.example/rust", "official_doc", "Rust editions", 4),
        ];
        var stub = new StubLlm();
        var recording = new RecordingLlm(stub);
        var acquirer = new KnowledgeAcquirer(ports with { Search = new InMemorySearch(seed), Llm = recording });
        var srcs = await acquirer.AcquireAsync(new("BIRDS", UseLlmBrief: true, TrustedTypes: ["paper"]), ct);
        var srcs2 = await acquirer.AcquireAsync(new("birds", ["paper", "model"], 1, new SourceQuality(0.9, 0.9, 0.9, 0.9, 0.9)), ct);
        var srcs3 = await acquirer.AcquireAsync(new("zzz", UseLlmBrief: true), ct);
        output["acquire"] = new JsonObject
        {
            ["srcs"] = J(srcs), ["srcs2"] = J(srcs2), ["srcs3"] = J(srcs3), ["prompts"] = Arr(recording.Prompts),
            ["stub"] = await stub.CompleteAsync(string.Concat(Enumerable.Repeat("  hello \n\n world  ", 10)), ct),
        };

        // verify
        var verifier = new EpistemicVerifier(ports, A, S);
        var v1 = await verifier.VerifyAsync(new(srcs, q1.Id, "birds migrate"), ct);
        var v2 = await verifier.VerifyAsync(new([srcs[2]], q1.Id, LikelihoodPerSource: 0.5), ct);
        var verErr = await ErrorOf(() => verifier.VerifyAsync(new([], "q"), ct));
        output["verify"] = new JsonObject { ["v1"] = J(v1), ["v2"] = J(v2), ["verErr"] = verErr, ["beliefs"] = Arr(storage.All<object>("belief")) };

        // synthesis
        var workbench = new SynthesisWorkbench(ports, A, S);
        var ka1 = await workbench.SynthesizeAsync(new(q1.Id, "learning_note", new JsonObject { ["summary"] = "s", ["confidence"] = v1.Confidence }, srcs, ["news"]), ct);
        var synErr = await ErrorOf(() => workbench.SynthesizeAsync(new(q1.Id, "learning_note", null, []), ct));
        output["synth"] = new JsonObject { ["ka1"] = J(ka1), ["synErr"] = synErr };

        // transfer
        var lab = new TransferLab(ports, A, S);
        var tr1 = await lab.ProposeAsync(new("chess", "go"), ct);
        var tr2 = await lab.ProposeAsync(new("chess", "shogi", Validated: true, InvariantsPreserved: ["tempo"], NegativeTransferSignal: 0.6, MeasuredOutcome: "worse"), ct);
        var tr3 = await lab.ProposeAsync(new("a", "b", PriorTransfer: tr2, NegativeTransferSignal: 0.3), ct);
        output["transfer"] = new JsonObject { ["tr1"] = J(tr1), ["tr2"] = J(tr2), ["tr3"] = J(tr3) };

        // journal
        var journal = new LifeJournal(ports, A, S);
        output["journal"] = new JsonObject
        {
            ["j1"] = J(await journal.ComposeAsync(new(), ct)),
            ["j2"] = J(await journal.ComposeAsync(new("2026-01-02", LearnedClaims: ["c"], SharePolicy: "shareable", EvidenceRefs: ["x"]), ct)),
        };

        // sharing
        var day = new SharingPolicy(ports with { Scheduler = new FixedScheduler(T0 + (3600_000 * 14)) }, A, S);
        var night = new SharingPolicy(ports with { Scheduler = new FixedScheduler(T0 + (3600_000 * 16)) }, A, S);
        output["sharing"] = Arr([
            await day.ScoreShareAsync("c1", U(1, 0), ct), await day.ScoreShareAsync("c2", U(0.5, 0.1), ct), await day.ScoreShareAsync("c3", U(0.3, 0.1), ct),
            await day.ScoreShareAsync("c4", U(0.1, 0.5), ct), await night.ScoreShareAsync("c5", U(1, 0), ct), await night.ScoreShareAsync("c6", U(0.5, 0.1), ct),
        ]);

        // evolution
        var signing = new InMemorySigning();
        var evoPorts = ports with { Signing = signing };
        var evolution = new EvolutionLab(evoPorts, A);
        CandidateVersion[] cands = [EvolutionLab.MakeCandidate("c1"), EvolutionLab.MakeCandidate("c2", deltaQuality: 0.5), EvolutionLab.MakeCandidate("c3", deltaQuality: 0.9, safety: 0.5)];
        var e1 = await evolution.EvaluateAsync(new(cands, EvolutionGrade.E2, "v1.0.0", "tune", "diff", "agent", "revert"), ct);
        var e2 = await evolution.EvaluateAsync(new(cands, EvolutionGrade.E1, "v1", "c", "d", "g", "r", Tests: [new("unit", true, "ev")],
            BenchmarkResults: new Dictionary<string, double> { ["acc"] = 0.9 }, SafetyResults: new Dictionary<string, object> { ["ok"] = true, ["n"] = 2 },
            MigrationPlan: "m", ApprovalPolicy: "human"), ct);
        var evErrs = new JsonArray(
            await ErrorOf(() => evolution.EvaluateAsync(new(cands, EvolutionGrade.E4, "v", "c", "d", "g", "r"), ct)),
            await ErrorOf(() => evolution.EvaluateAsync(new([EvolutionLab.MakeCandidate("bad", rollbackAvailable: false)], EvolutionGrade.E1, "v", "c", "d", "g", "r"), ct)),
            await ErrorOf(() => evolution.EvaluateAsync(new(cands, EvolutionGrade.E1, "v", "c", "d", "g", " "), ct)));
        output["evolution"] = new JsonObject { ["e1"] = J(e1), ["e2"] = J(e2), ["evErrs"] = evErrs };

        // release
        var controller = new TrustedReleaseController(evoPorts, A);
        var pack = new EvaluationEvidencePack("pack-1", e1.Proposal.Id, new CoreTestGate(true, 10, 0), T0);
        var r1 = await controller.ReleaseAsync(e1.Proposal, pack, cancellationToken: ct);
        var r2 = await controller.ReleaseAsync(e1.Proposal, pack with { StaticAnalysis = new GateResult(false) }, cancellationToken: ct);
        var r3 = await controller.ReleaseAsync(e1.Proposal, pack with { UnitContractPropertyTests = new CoreTestGate(false, 10, 1) }, cancellationToken: ct);
        var r4 = await controller.ReleaseAsync(e2.Proposal, pack, "human-1", 7, ct);
        var r5 = await controller.ReleaseAsync(e1.Proposal with { RollbackPlan = "" }, pack, cancellationToken: ct);
        output["release"] = new JsonObject { ["r1"] = J(r1), ["r2"] = J(r2), ["r3"] = J(r3), ["r4"] = J(r4), ["r5"] = J(r5) };

        var executor = new ReleaseExecutor(ports);
        var rexOut = new List<object?> { await executor.SelectAsync(new(UserId: "u1"), "tr-0", ct) };
        await executor.ActivateAsync(r1.Release!, cancellationToken: ct);
        rexOut.Add(await executor.ActiveAsync(ct));
        foreach (var id in new[] { "u1", "u2", "u3", "u4", "u5", "u6", "u7", "u8" })
            rexOut.Add(await executor.SelectAsync(new(UserId: id), $"tr-{id}", ct));
        rexOut.Add(await executor.SelectAsync(new(SessionId: "s9"), cancellationToken: ct));
        await executor.ActivateAsync(r4.Release!, T0 + 5, ct);
        rexOut.Add(storage.All<object>("release_execution"));
        rexOut.Add(await executor.SelectAsync(new(UserId: " u2 "), "tr-full", ct));
        var rexErr = new JsonArray(
            await ErrorOf(() => executor.RollbackAsync("wrong", "r", cancellationToken: ct)),
            await ErrorOf(() => executor.RollbackAsync(r4.Release!.Id, "  ", cancellationToken: ct)),
            await ErrorOf(() => executor.ActivateAsync(r1.Release! with { RollbackAvailable = false }, cancellationToken: ct)));
        await executor.RollbackAsync(r4.Release!.Id, "regression", cancellationToken: ct);
        rexOut.Add(await executor.ActiveAsync(ct));
        rexOut.Add(await executor.SelectAsync(new(UserId: "u1"), "tr-after", ct));
        rexOut.Add(storage.All<object>("release_routing_trace"));
        output["executor"] = new JsonObject { ["rexOut"] = Arr(rexOut), ["rexErr"] = rexErr };

        // critic
        var critic = new ArchitectureCritic(ports, A, S);
        output["critic"] = J(await critic.ScanAsync(
            [q1, q2, q1 with { Status = "abandoned" }, q1 with { Status = "needs_consent" }, q1 with { Status = "active" }, q1 with { Status = "paused" }],
            [e1.Proposal, e1.Proposal with { Id = "p5", Grade = "E5" }, e1.Proposal with { Id = "p4", Grade = "E4" }],
            [tr1, tr2, tr3], ct));

        // performance
        var director = new PerformanceDirector(ports, A, S);
        output["perf"] = Arr([
            await director.DirectAsync(new("snap-1", new PersonaInput(DialogueAct.Inform), StepCount: 3, Duration: 150), ct),
            await director.DirectAsync(new("snap-2", new PersonaInput(DialogueAct.Question, Character: new PartialExpression(Valence: 0.8, Arousal: 0.9),
                Relationship: new RelationshipModel(Intimacy: 0.9)), [new ConsistencyObservation(ClothingDrift: 0.5), new ConsistencyObservation(FaceIdentityDrift: 0.1)],
                DuplexEvents: [DuplexEvent.UserInterruption, DuplexEvent.ListenSignal]), ct),
            await director.DirectAsync(new("snap-3", new PersonaInput(DialogueAct.Comfort), [new ConsistencyObservation(ClothingDrift: 0.5, FaceIdentityDrift: 0.5)], StepCount: 0), ct),
        ]);

        // growth loop
        var runIn = new RunOnceInput("birds", ["e1"], comps, 0.7, 0.6, 0.5, "why migrate", "def", 0.5, QuestionType.Everyday, "birds");
        var gStore = new InMemoryStorage();
        var loop = new GrowthLoop(new GrowthPorts(gStore, new FixedScheduler(T0 + (3600_000 * 14)), new InMemorySearch(seed), signing, new StubLlm(), ids, Seoul), A, S);
        var g1 = await loop.RunOnceAsync(runIn, ct);
        var g2 = await loop.RunOnceAsync(runIn with { Query = "nothing-matches", ShareUtility = U(0.2, 0.05) }, ct);
        var budgeted = new InMemoryScheduler(new Dictionary<string, double> { ["growth_loop"] = 1 }, new MutableTime(() => clock));
        var loop2 = new GrowthLoop(new GrowthPorts(new InMemoryStorage(), budgeted, new InMemorySearch(seed), signing, null, ids, Seoul), A, S);
        clock = T0 + (3600_000 * 14);
        var g3 = await loop2.RunOnceAsync(runIn, ct);
        var g4 = await loop2.RunOnceAsync(runIn, ct);
        var dump = new JsonObject();
        foreach (var k in new[] { "interest_thread", "learning_quest", "source_record", "claim_map", "belief", "knowledge_artifact", "life_journal_entry", "share_candidate" })
            dump[k] = Arr(gStore.All<object>(k));
        output["loop"] = new JsonObject { ["g1"] = J(g1), ["g2"] = J(g2), ["g3"] = J(g3), ["g4"] = J(g4), ["dump"] = dump };

        // The executor section of the golden data predates the release-storage fix (see ReleaseExecutor), so it is checked
        // separately against the corrected behaviour.
        var golden = Golden.DeepClone().AsObject();
        golden.Remove("executor");
        var executorOut = output["executor"]!;
        output.Remove("executor");
        var diffs = new List<string>();
        JsonEquivalence.Collect(golden, output, "$", diffs);
        AssertFixedExecutor(executorOut, r1.Release!, r4.Release!);
        Assert.True(diffs.Count == 0, string.Join("\n", diffs.Take(40)));
    }

    private static void AssertFixedExecutor(JsonNode executor, SignedRelease canary, SignedRelease full)
    {
        var o = executor["rexOut"]!.AsArray();
        var errs = Golden["executor"]!["rexErr"]!.AsArray().Select(e => e!.GetValue<string>());
        Assert.Equal(errs, executor["rexErr"]!.AsArray().Select(e => e!.GetValue<string>()));
        Assert.False(o[0]!["eligible"]!.GetValue<bool>()); // nothing active yet
        Assert.Equal(canary.Id, o[1]!["id"]!.GetValue<string>()); // active() now returns the canary release
        // Canary 0.1: exactly the users whose stable bucket is below 0.1 are routed (all eight u* buckets are ≥ 0.9).
        for (var i = 2; i <= 10; i++)
        {
            Assert.Equal(0.1, o[i]!["canaryRatio"]!.GetValue<double>());
            Assert.Equal(o[i]!["bucket"]!.GetValue<double>() < 0.1, o[i]!["eligible"]!.GetValue<bool>());
            Assert.Equal(Golden["executor"]!["rexOut"]![i]!["bucket"]!.GetValue<double>(), o[i]!["bucket"]!.GetValue<double>());
        }
        var full2 = o[12]!; // after activating the full (ratio 1) release, everyone is routed to it
        Assert.True(full2["eligible"]!.GetValue<bool>());
        Assert.Equal(full.Version, full2["version"]!.GetValue<string>());
        Assert.Null(o[13]); // rolled back
        Assert.False(o[14]!["eligible"]!.GetValue<bool>());
    }

    private static JsonObject SignPayload() => new()
    {
        ["b"] = 1,
        ["a"] = new JsonArray(1.5, "x"),
        ["c"] = new JsonObject { ["z"] = null },
    };

    [Fact]
    public void Crypto_signing_verifies_and_rejects_tampering()
    {
        var signer = new CryptoSigningAdapter("secret");
        var payload = new JsonObject { ["v"] = "1.0", ["n"] = 3 };
        var sig = signer.Sign(payload);
        Assert.True(signer.Verify(new JsonObject { ["n"] = 3, ["v"] = "1.0" }, sig)); // key order does not matter
        Assert.False(signer.Verify(new JsonObject { ["v"] = "1.1", ["n"] = 3 }, sig));
        Assert.False(signer.Verify(payload, "not-hex"));
        Assert.False(new CryptoSigningAdapter("other").Verify(payload, sig));
        Assert.False(signer.UsingDevSecret);
    }

    [Fact]
    public async Task File_storage_round_trips_records_and_survives_restarts()
    {
        var ct = TestContext.Current.CancellationToken;
        var dir = Directory.CreateTempSubdirectory("aijade-growth-").FullName;
        try
        {
            var ports = new GrowthPorts(new FileStorageAdapter(dir), new FixedScheduler(T0), new InMemorySearch(), Ids: new GrowthIds(() => T0, () => 0.5), TimeZone: TimeZoneInfo.Utc);
            var thread = await new InterestService(ports, A, S).CreateThreadAsync(new("Birds", ["e1"], new InterestComponents(0.6, 0.5, 0.7, 0.5, 0.6, 0.5, 0.2, 0.1, 0.1), 0.8, 0.3, 0.5), ct);
            var reopened = new InterestService(ports with { Storage = new FileStorageAdapter(dir) }, A, S);
            Assert.Equal(thread, (await reopened.GetAsync(thread.Id, ct))! with { OriginEventIds = thread.OriginEventIds, MotivatingQuestions = thread.MotivatingQuestions, KnowledgeGaps = thread.KnowledgeGaps, CurrentHypotheses = thread.CurrentHypotheses });
            Assert.Single(await reopened.ListAsync(ct));
            Assert.Null(await new FileStorageAdapter(dir).GetAsync<InterestThread>("interest_thread", "missing", ct));
            Assert.Equal("a_b_.._c", FileStorageAdapter.Safe("a/b/../c"));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void System_scheduler_refills_tokens_and_persists_the_ledger()
    {
        var dir = Directory.CreateTempSubdirectory("aijade-ledger-").FullName;
        try
        {
            var now = T0;
            var time = new MutableTime(() => now);
            var ledger = Path.Combine(dir, "ledger.json");
            var budgets = new Dictionary<string, BudgetPolicy> { ["g"] = new(2, 1) };
            var s = new SystemSchedulerAdapter(budgets, ledger, time);
            Assert.True(s.ConsumeBudget("g", 1));
            Assert.True(s.ConsumeBudget("g", 1));
            Assert.False(s.ConsumeBudget("g", 1));
            Assert.True(s.ConsumeBudget("unlisted", 1000));
            now += 1500; // 1.5 tokens refilled
            var restarted = new SystemSchedulerAdapter(budgets, ledger, time);
            Assert.True(restarted.ConsumeBudget("g", 1));
            Assert.Equal(0.5, restarted.Snapshot()["g"], 9);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task Hashed_vector_search_ranks_by_similarity_within_scopes()
    {
        var ct = TestContext.Current.CancellationToken;
        var search = new HashedVectorSearch(
        [
            new("doc://birds", "doc", "Birds migrate south every winter to find food"),
            new("doc://rust", "doc", "Rust editions change the language every three years"),
            new("data://birds", "data", "migration counts of birds by month"),
        ], limit: 2, time: new FixedTime(1));
        var hits = await search.SearchAsync("why do birds migrate in winter", [], ct);
        Assert.Equal("doc://birds", hits[0].Locator);
        Assert.Equal(2, hits.Count);
        var scoped = await search.SearchAsync("birds", ["data"], ct);
        Assert.Equal(["data://birds"], scoped.Select(h => h.Locator));
        Assert.Empty(await search.SearchAsync("", ["doc"], ct)); // an empty query has a zero vector: nothing is similar
        Assert.Equal(1, hits[0].FetchedAt);
    }

    [Fact]
    public async Task Hashed_vector_search_reads_a_document_directory()
    {
        var ct = TestContext.Current.CancellationToken;
        var dir = Directory.CreateTempSubdirectory("aijade-corpus-").FullName;
        try
        {
            await File.WriteAllTextAsync(Path.Combine(dir, "b.md"), "  birds migrate  ", ct);
            await File.WriteAllTextAsync(Path.Combine(dir, "a.json"), "{\"x\":1}", ct);
            await File.WriteAllTextAsync(Path.Combine(dir, "empty.txt"), "   ", ct);
            await File.WriteAllTextAsync(Path.Combine(dir, "skip.bin"), "birds", ct);
            var corpus = HashedVectorSearch.CorpusFromDirectory(dir);
            Assert.Equal(["data", "doc"], corpus.Select(c => c.SourceType));
            Assert.Equal("birds migrate", corpus[1].Content);
            Assert.Equal(2, new HashedVectorSearch(searchDir: dir).Count);
            Assert.Empty(HashedVectorSearch.CorpusFromDirectory(Path.Combine(dir, "missing")));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public async Task Real_ports_wire_file_storage_and_a_budgeted_loop()
    {
        var ct = TestContext.Current.CancellationToken;
        var dir = Directory.CreateTempSubdirectory("aijade-real-").FullName;
        try
        {
            var options = new RealPortsOptions(dir, "s", StubLlm: true, Budgets: new Dictionary<string, BudgetPolicy> { ["growth_loop"] = new(1, 0) },
                SearchCorpus: [new("doc://birds", "doc", "birds migrate south")]);
            var loop = RealPorts.CreateGrowthLoop(options, A, S);
            var input = new RunOnceInput("birds", ["e1"], new InterestComponents(0.6, 0.5, 0.7, 0.5, 0.6, 0.5, 0.2, 0.1, 0.1), 0.7, 0.6, 0.5, "why migrate", "def",
                0.5, QuestionType.Everyday, "birds migrate");
            var first = await loop.RunOnceAsync(input, ct);
            Assert.False(first.Skipped);
            Assert.Equal(2, first.SourceCount); // the corpus hit plus the stub LLM brief
            Assert.True((await RealPorts.CreateGrowthLoop(options, A, S).RunOnceAsync(input, ct)).Skipped); // ledger persisted across instances
            Assert.True(File.Exists(Path.Combine(dir, "scheduler-ledger.json")));
            Assert.NotEmpty(Directory.GetFiles(Path.Combine(dir, "storage", "learning_quest")));
            Assert.Throws<ArgumentException>(() => RealPorts.Create(new RealPortsOptions(dir)));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void Ids_follow_the_original_scheme()
    {
        var ids = new GrowthIds(() => 1_700_000_000_000, () => 0.5);
        Assert.Equal("x_loyw3v28_1_4zsov", ids.NewId("x"));
        Assert.Equal("0", GrowthUtil.Base36(0));
        Assert.Equal("zz", GrowthUtil.Base36(1295));
        Assert.Matches("^q_[0-9a-z]+_[0-9a-z]+_[0-9a-z]+$", GrowthIds.Shared.NewId("q"));
    }
}

/// <summary>Semantic JSON comparison against recorded output: object member order ignored, "schema" tags ignored, absent ≡ null, numbers as doubles.</summary>
internal static class JsonEquivalence
{
    public static void Collect(JsonNode? expected, JsonNode? actual, string path, List<string> diffs)
    {
        switch (expected)
        {
            case null:
                if (actual is not null)
                    diffs.Add($"{path}: expected null/absent, got {actual.ToJsonString()}");
                return;
            case JsonObject eo:
                if (actual is not JsonObject ao)
                {
                    diffs.Add($"{path}: expected object, got {actual?.ToJsonString() ?? "null"}");
                    return;
                }
                foreach (var key in eo.Select(kv => kv.Key).Union(ao.Select(kv => kv.Key)).Where(k => k != "schema"))
                    Collect(eo[key], ao[key], $"{path}.{key}", diffs);
                return;
            case JsonArray ea:
                if (actual is not JsonArray aa)
                {
                    diffs.Add($"{path}: expected array, got {actual?.ToJsonString() ?? "null"}");
                    return;
                }
                if (ea.Count != aa.Count)
                    diffs.Add($"{path}: expected {ea.Count} items, got {aa.Count}");
                for (var i = 0; i < Math.Min(ea.Count, aa.Count); i++)
                    Collect(ea[i], aa[i], $"{path}[{i}]", diffs);
                return;
            case JsonValue ev:
                if (actual is not JsonValue av)
                {
                    diffs.Add($"{path}: expected {ev.ToJsonString()}, got {actual?.ToJsonString() ?? "null"}");
                    return;
                }
                if (ev.GetValueKind() == JsonValueKind.Number && av.GetValueKind() == JsonValueKind.Number)
                {
                    var x = double.Parse(ev.ToJsonString(), CultureInfo.InvariantCulture);
                    var y = double.Parse(av.ToJsonString(), CultureInfo.InvariantCulture);
                    if (x != y)
                        diffs.Add($"{path}: expected {ev.ToJsonString()}, got {av.ToJsonString()}");
                }
                else if (ev.ToJsonString() != av.ToJsonString())
                {
                    diffs.Add($"{path}: expected {ev.ToJsonString()}, got {av.ToJsonString()}");
                }
                return;
        }
    }
}
