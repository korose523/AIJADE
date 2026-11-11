using Aijade.Research.SkillBench;

using Npgsql;

namespace Aijade.Tests;

public partial class ResearchEvidenceTests
{
    [Fact]
    public async Task Both_conditions_preserve_execution_and_actual_admitted_proposal_checks()
    {
        var ct = TestContext.Current.CancellationToken;
        foreach (var condition in Enum.GetValues<ResearchConstraintCondition>())
        {
            await using var host = await ServerTestHost.StartAsync(worker: false);
            await ResearchLoopAdapter.InitializeAsync(host);
            await AdmitAsync(host);
            var adapter = new ResearchLoopAdapter(host, condition);
            var unknown = await adapter.CommitAsync("unknown", Evidence with { ExecutionOk = null }, Proposal("p"), "admitted", ct);
            var failed = await adapter.CommitAsync("failed", Evidence with { ExecutionOk = false, Passed = 4 }, Proposal("p"), "admitted", ct);
            var absent = await adapter.CommitAsync("absent", Evidence, Proposal("p"), "absent", ct);
            var different = await adapter.CommitAsync("different", Evidence, Proposal("different"), "admitted", ct);
            Assert.Equal("execution_unknown", unknown.Outcome.Reason);
            Assert.Equal("execution_failed", failed.Outcome.Reason);
            Assert.Equal("admission_refused", absent.Outcome.Reason);
            Assert.Equal("admission_proposal_mismatch", different.Outcome.Reason);
            Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM evolution_specs"));
            Assert.Empty(adapter.PromotionAttempts);
        }
    }

    [Fact]
    public async Task Only_the_declared_cross_record_condition_rejects_a_foreign_receipt_binding()
    {
        var ct = TestContext.Current.CancellationToken;
        foreach (var condition in Enum.GetValues<ResearchConstraintCondition>())
        {
            await using var host = await ServerTestHost.StartAsync(worker: false);
            await ResearchLoopAdapter.InitializeAsync(host);
            await AdmitAsync(host);
            var adapter = new ResearchLoopAdapter(host, condition);
            var result = await adapter.CommitAsync("binding", Evidence with { ReceiptIntentId = "foreign" }, Proposal("p"), "admitted", ct);
            Assert.Equal(condition == ResearchConstraintCondition.ModuleLocal, result.Outcome.Promoted);
            Assert.Equal(condition == ResearchConstraintCondition.ModuleLocal ? "qualified" : "execution_intent_mismatch", result.Outcome.Reason);
        }
    }

    [Fact]
    public async Task Both_conditions_deduplicate_and_keep_current_revocation_terminal()
    {
        var ct = TestContext.Current.CancellationToken;
        foreach (var condition in Enum.GetValues<ResearchConstraintCondition>())
        {
            await using var host = await ServerTestHost.StartAsync(worker: false);
            await ResearchLoopAdapter.InitializeAsync(host);
            await AdmitAsync(host);
            var adapter = new ResearchLoopAdapter(host, condition);
            var calls = await Task.WhenAll(adapter.CommitAsync("once", Evidence, Proposal("p"), "admitted", ct),
                adapter.CommitAsync("once", Evidence, Proposal("p"), "admitted", ct));
            Assert.Single(calls, c => c.Duplicate);
            Assert.Single(adapter.PromotionAttempts);
            var delivery = await adapter.DeliverAsync("once");
            Assert.Equal(201, delivery["httpStatus"]!.GetValue<int>());
            Assert.True((await adapter.DeliverAsync("once"))["duplicate"]!.GetValue<bool>());
            var task = Bench.Tasks.Single(t => t.Id == Evidence.TaskId);
            Assert.True((await adapter.Round2Async("once", Evidence.SkillId, Code, task, ct))["executed"]!.GetValue<bool>());
            Assert.False((await adapter.Round2Async("once", Evidence.SkillId, Code, task, ct))["executed"]!.GetValue<bool>());
            await adapter.RevokeAsync(Evidence.SkillId, ct);
            var stale = await adapter.Round2Async("once", Evidence.SkillId, Code, task, ct);
            Assert.Equal("authority_revoked", stale["reason"]!.GetValue<string>());
            Assert.True(stale["retrieved"]!.GetValue<bool>());
            var replay = await adapter.CommitAsync("old-after-revocation", Evidence, Proposal("p"), "admitted", ct);
            Assert.False(replay.Outcome.Promoted);
            Assert.Equal("revoked", replay.Outcome.State);
            Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM evolution_specs"));
            Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM research_reuses"));
        }
    }

    [Fact]
    public async Task A_successful_service_return_is_distinct_from_committed_effects_in_both_transaction_modes()
    {
        var ct = TestContext.Current.CancellationToken;
        foreach (var condition in Enum.GetValues<ResearchConstraintCondition>())
        {
            await using var host = await ServerTestHost.StartAsync(worker: false);
            await ResearchLoopAdapter.InitializeAsync(host);
            await AdmitAsync(host);
            await host.ExecAsync("""
                CREATE FUNCTION reject_comparison_authority() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    IF (SELECT count(*) FROM evolution_specs) <> 1 OR (SELECT count(*) FROM eval_reports) <> 1 THEN
                        RAISE EXCEPTION 'promotion rows not visible' USING ERRCODE='P0002';
                    END IF;
                    RAISE EXCEPTION 'declared authority fault' USING ERRCODE='P0001'; END $$;
                CREATE TRIGGER reject_comparison_authority_write BEFORE INSERT ON research_skill_authority
                FOR EACH ROW EXECUTE FUNCTION reject_comparison_authority();
                """);
            var adapter = new ResearchLoopAdapter(host, condition);
            var error = await Assert.ThrowsAsync<PostgresException>(() => adapter.CommitAsync("fault", Evidence, Proposal("p"), "admitted", ct));
            Assert.Equal("P0001", error.SqlState);
            Assert.True(Assert.Single(adapter.PromotionAttempts)["serviceResult"]!["ok"]!.GetValue<bool>());
            var expectedRows = condition == ResearchConstraintCondition.ModuleLocal ? 1 : 0;
            Assert.Equal(expectedRows, await host.CountAsync("SELECT count(*) FROM evolution_specs"));
            Assert.Equal(expectedRows, await host.CountAsync("SELECT count(*) FROM eval_reports"));
            Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM research_skill_authority"));
            Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM research_outbox"));
        }
    }
}
