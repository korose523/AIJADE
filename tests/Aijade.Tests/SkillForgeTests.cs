using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Learning.Forge;
using Aijade.Learning.Skills;
using Aijade.Providers.Llm;

namespace Aijade.Tests;

/// <summary>The skill forge must equal the recorded golden data (schema issue texts, SKILL.md, prompts) and keep its behaviour.</summary>
public class SkillForgeTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "skill-forge-golden.json"))).RootElement;

    private static SkillBody Body(JsonElement b) => new(b.GetProperty("title").GetString()!, Strs(b, "whenToUse")!, Strs(b, "procedure")!, Str(b, "intro"),
        Strs(b, "prerequisites"), Str(b, "howToRun"), Strs(b, "quickReference"), Strs(b, "pitfalls"), Str(b, "verification"));

    private static string? Str(JsonElement o, string k) => o.TryGetProperty(k, out var v) ? v.GetString() : null;

    private static List<string>? Strs(JsonElement o, string k) => o.TryGetProperty(k, out var v) ? v.EnumerateArray().Select(x => x.GetString()!).ToList() : null;

    private static (SkillFrontmatter, SkillBody) Valid() => SkillSchema.Parse(JsonNode.Parse(Golden.GetProperty("cases")[0].GetRawText()));

    [Fact]
    public void Schema_issues_markdown_and_prompts_match_the_original()
    {
        foreach (var (c, expected) in Golden.GetProperty("cases").EnumerateArray().Zip(Golden.GetProperty("validation").EnumerateArray()))
            Assert.Equal(expected.EnumerateArray().Select(x => x.GetString()), SkillSchema.Validate(JsonNode.Parse(c.GetRawText())));

        var (fm, body) = Valid();
        var pkg = new SkillPackage(fm, body, 1, 1, SkillSource.HandAuthored, []);
        Assert.Equal(Golden.GetProperty("md").GetString(), SkillMarkdown.ToMarkdown(pkg));
        var minimal = new SkillPackage(new SkillFrontmatter("n", "D \"quoted\".", "0.1.0", "AIJADE"), new SkillBody("T", ["a"], ["b"]), 1, 1, SkillSource.HandAuthored, []);
        Assert.Equal(Golden.GetProperty("md2").GetString(), SkillMarkdown.ToMarkdown(minimal));
        foreach (var (md, key) in new[] { (SkillMarkdown.ToMarkdown(pkg), "parsed"), (SkillMarkdown.ToMarkdown(minimal), "parsed2") })
        {
            var (pfm, pbody) = SkillMarkdown.Parse(md);
            var e = Golden.GetProperty(key);
            Assert.Equal(JsFormat.CanonicalJson(JsonNode.Parse(e.GetProperty("frontmatter").GetRawText())), JsFormat.CanonicalJson(pfm));
            Assert.Equal(JsFormat.CanonicalJson(JsonNode.Parse(e.GetProperty("body").GetRawText())), JsFormat.CanonicalJson(SkillSchema.ToJson(new SkillFrontmatter("x", "x.", "0.1.0", "a"), pbody)["body"]));
        }

        var p = Golden.GetProperty("prompts");
        var draft = new SkillDraft("git-rebase-recipe", "Git Rebase", "Rebases a feature branch onto main.", ["behind main", "before a PR"]);
        Assert.Equal(p.GetProperty("teach").GetString(), SkillPrompts.TeachableMoment("user: hi\n\nassistant: hello"));
        Assert.Equal(p.GetProperty("gen").GetString(), SkillPrompts.Generation(draft));
        Assert.Equal(p.GetProperty("val").GetString(), SkillPrompts.Validation(fm, body));
        Assert.Equal(p.GetProperty("evo").GetString(), SkillPrompts.Evolution(fm, body, "add a step for force-push"));
        Assert.Equal(p.GetProperty("valMin").GetString(), SkillPrompts.Validation(minimal.Frontmatter, minimal.Body));
        Assert.Equal(p.GetProperty("evoMin").GetString(), SkillPrompts.Evolution(minimal.Frontmatter, minimal.Body, "f"));
    }

    /// <summary>Answers JSON requests in order from a script; records every prompt.</summary>
    private sealed class ScriptedChat(params Func<string, string>[] replies) : IChatClient
    {
        private int _i;

        public List<string> Prompts { get; } = [];

        public string Model => "scripted";

        public Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default)
        {
            var prompt = messages[^1].Content;
            Prompts.Add(prompt);
            return Task.FromResult(ChatParsing.ParseJsonContent(replies[Math.Min(_i++, replies.Length - 1)](prompt)));
        }
    }

    private static string SkillJson(string description = "Rebases a feature branch onto main.") =>
        JsonNode.Parse(Golden.GetProperty("cases")[0].GetRawText())!.AsObject() is var o && (o["frontmatter"]!["description"] = description) is not null ? o.ToJsonString() : "";

    [Fact]
    public async Task Forge_detects_generates_repairs_validates_and_evolves()
    {
        var ct = TestContext.Current.CancellationToken;
        var chat = new ScriptedChat(
            _ => """Sure: {"shouldCreate":true,"rationale":"repeatable","draft":{"proposedName":"git-rebase-recipe","title":"Git Rebase","summary":"Rebases.","whenToUse":["behind main"]}}""",
            _ => SkillJson("Rebases branches."),
            _ => """{"ok":false,"warnings":["w1"],"score":0.4}""",
            _ => $"```json\n{SkillJson()}\n```",
            _ => """{"ok":true,"warnings":[],"score":0.8}""");
        var forge = new SkillForge(chat, now: () => 5);
        var draft = await forge.DetectTeachableMomentAsync([new ChatMessage(ChatRole.User, "how do I rebase?"), new ChatMessage(ChatRole.Assistant, "git rebase origin/main")], ct);
        Assert.Equal("git-rebase-recipe", draft!.ProposedName);
        Assert.Contains("user: how do I rebase?\n\nassistant: git rebase origin/main", chat.Prompts[0], StringComparison.Ordinal);

        var pkg = await forge.GenerateSkillAsync(draft, ct);
        Assert.Equal("Rebases a feature branch onto main.", pkg.Frontmatter.Description);
        // The reviewer rejected the first draft, so the repair prompt carries its error; the repaired version scores higher and wins.
        Assert.EndsWith("PREVIOUS ERRORS TO FIX:\n- LLM reviewer judged the skill unsafe/incomplete.", chat.Prompts[3], StringComparison.Ordinal);
        // A structurally invalid generation is not repaired: it fails the schema and throws.
        await Assert.ThrowsAsync<SkillSchemaException>(() => new SkillForge(new ScriptedChat(_ => SkillJson("x".PadRight(70, 'x') + "."))).GenerateSkillAsync(draft, ct));
        Assert.Equal(SkillSource.LlmGenerated, pkg.Source);

        Assert.Null(await new SkillForge(new ScriptedChat(_ => """{"shouldCreate":false,"rationale":"chit-chat"}""")).DetectTeachableMomentAsync([new ChatMessage(ChatRole.User, "hi")], ct));
        Assert.Null(await forge.DetectTeachableMomentAsync([], ct));

        var evolved = await new SkillForge(new ScriptedChat(_ => SkillJson()), now: () => 9).EvolveSkillAsync(pkg with { Frontmatter = pkg.Frontmatter with { Version = "0.1.9" } }, "add force-push", ct);
        Assert.Equal(("0.1.10", SkillSource.Evolved, 1), (evolved.Frontmatter.Version, evolved.Source, evolved.EvolutionLog.Count));
        Assert.Equal("evolved git-rebase-recipe from 0.1.9 -> 0.1.10", evolved.EvolutionLog[0].Summary);
        Assert.Equal("1.x", SkillForge.BumpVersion("1.x"));
    }

    [Fact]
    public async Task Validation_scores_sandbox_and_reviewer()
    {
        var ct = TestContext.Current.CancellationToken;
        var (fm, body) = Valid();
        var pkg = new SkillPackage(fm, body, 1, 1, SkillSource.HandAuthored, []);
        var ok = await new SkillForge(new ScriptedChat(_ => """{"ok":true,"warnings":["a"],"score":0.6}""")).ValidateSkillAsync(pkg, ct);
        Assert.Equal((true, 0.8), (ok.Ok, ok.Score));
        var unsafeResult = await new SkillForge(new ScriptedChat(_ => """{"ok":false,"warnings":[],"score":0.2}""")).ValidateSkillAsync(pkg, ct);
        Assert.Contains("LLM reviewer judged the skill unsafe/incomplete.", unsafeResult.Errors);
        var noReviewer = await new SkillForge(new ScriptedChat(_ => "not json"), sandbox: _ => Task.FromResult((false, "crashed"))).ValidateSkillAsync(pkg, ct);
        Assert.Equal(0.3, noReviewer.Score, 12);
        Assert.Contains("sandbox: crashed", noReviewer.Errors);
        Assert.StartsWith("LLM self-check skipped", noReviewer.Warnings[0], StringComparison.Ordinal);
        var badStructure = await new SkillForge(new ScriptedChat(_ => """{"ok":true,"warnings":[],"score":1}""")).ValidateSkillAsync(pkg with { Frontmatter = fm with { Name = "Bad Name" } }, ct);
        Assert.Equal((false, 0.3), (badStructure.Ok, badStructure.Score));

        var forge = new SkillForge(new ScriptedChat(_ => "{}"));
        Assert.True(forge.Register(pkg).Registered);
        Assert.False(forge.Register(pkg with { Body = body with { Procedure = [] } }).Registered);
    }

    [Fact]
    public void Measured_registry_tracks_lifecycle_and_persists()
    {
        var hello = Skills.Define("hello", "Greet the user warmly.", new SkillBody("Hello", ["when greeting"], ["say hi"]), now: 7);
        Assert.Equal(("0.1.0", "AIJADE", SkillSource.HandAuthored, 7.0), (hello.Frontmatter.Version, hello.Frontmatter.Author, hello.Source, hello.CreatedAt));

        var reg = new MeasuredSkillRegistry();
        reg.Add(hello);
        reg.Add(hello with { Frontmatter = hello.Frontmatter with { Name = "flaky" } });
        reg.SetSelfVerification("hello", SkillVerdict.Pass);
        reg.SetSelfVerification("flaky", SkillVerdict.Pass);
        reg.RecordExecution("hello", new ExecutionOutcome(true));
        foreach (var _ in Enumerable.Range(0, 3))
            reg.RecordExecution("flaky", new ExecutionOutcome(false));
        var m = reg.Metrics();
        Assert.Equal((2, 1, 1, 1), (m.Total, m.Retired, m.Active, m.ExecSuccess));
        Assert.Equal(0.5, m.SelfVerificationHallucinationRate, 5);
        Assert.True(reg.Remove("hello"));
        Assert.False(reg.Has("hello"));

        var file = Path.Combine(Path.GetTempPath(), $"skills-{Guid.NewGuid():N}", "skills.jsonl");
        try
        {
            var a = new MeasuredSkillRegistry(file: file);
            a.Add(hello);
            a.RecordExecution("hello", new ExecutionOutcome(true));
            var b = new MeasuredSkillRegistry(file: file);
            Assert.Equal("Greet the user warmly.", b.Find("hello")!.Frontmatter.Description);
            Assert.Equal(["say hi"], b.Find("hello")!.Body.Procedure);
            Assert.Equal((1, 1, 1.0), (b.Metrics().Total, b.Metrics().ExecSuccess, b.Metrics().Precision));
            Assert.Contains("\"record\":{\"skillId\":\"hello\"", File.ReadAllText(file), StringComparison.Ordinal);
        }
        finally
        {
            Directory.Delete(Path.GetDirectoryName(file)!, true);
        }
    }

    [Fact]
    public void Chat_parsing_tolerates_fences_prose_and_missing_fields()
    {
        var c = ChatParsing.ParseCompletion(JsonNode.Parse("""{"id":"chatcmpl-1","model":"qwen2.5:7b","choices":[{"index":0,"message":{"role":"assistant","content":"hello"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":3,"total_tokens":13}}"""), "fallback");
        Assert.Equal(("hello", "qwen2.5:7b", "stop", 13.0), (c.Text, c.Model, c.FinishReason, c.Usage!.TotalTokens));
        var empty = ChatParsing.ParseCompletion(new JsonObject(), "fallback");
        Assert.Equal(("", "fallback"), (empty.Text, empty.Model));
        Assert.Null(empty.Usage);
        Assert.Equal(1, ChatParsing.ParseJsonContent("""{"a":1}""")!["a"]!.GetValue<int>());
        Assert.Equal(2, ChatParsing.ParseJsonContent("```json\n{\"a\":[1,2]}\n```")!["a"]![1]!.GetValue<int>());
        Assert.True(ChatParsing.ParseJsonContent("""Sure! Here is the result: {"ok":true} hope that helps""")!["ok"]!.GetValue<bool>());
        Assert.ThrowsAny<Exception>(() => ChatParsing.ParseJsonContent("not json at all"));
        Assert.Throws<FormatException>(() => ChatParsing.ParseJsonContent("   "));
    }
}
