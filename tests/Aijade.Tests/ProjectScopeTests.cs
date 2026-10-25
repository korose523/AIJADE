using System.Text.Json;
using System.Xml.Linq;

namespace Aijade.Tests;

/// <summary>
/// The research line must not depend on the non-research line (docs/PROJECT-SCOPE.md, docs/decisions/ADR-001.md).
/// configs/project-scope.json assigns every module to a line and says which lines each line may reference; these checks
/// hold the directory tree and the project references to it. They are static: they say nothing about whether a study's
/// results hold, and a dynamic call (HTTP, files) between lines is not seen by them.
/// </summary>
public class ProjectScopeTests
{
    private sealed record Module(string Path, string Line, IReadOnlyList<string> ResearchObjects);

    private sealed record Scope(IReadOnlyDictionary<string, string[]> Lines, IReadOnlyList<Module> Modules);

    /// <summary>Directories whose immediate subdirectories are modules.</summary>
    private static readonly string[] ModuleParents = ["src", "tools", "tests", "integrations"];

    /// <summary>Directories that hold build output or dependencies, never sources.</summary>
    private static readonly string[] Skipped = ["bin", "obj", "node_modules", ".git"];

    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    private static Scope Load()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "project-scope.json")));
        var lines = doc.RootElement.GetProperty("lines").EnumerateObject().ToDictionary(
            p => p.Name,
            p => p.Value.GetProperty("mayReference").EnumerateArray().Select(e => e.GetString()!).ToArray(),
            StringComparer.Ordinal);
        var modules = doc.RootElement.GetProperty("modules").EnumerateArray().Select(m => new Module(
            m.GetProperty("path").GetString()!,
            m.GetProperty("line").GetString()!,
            m.TryGetProperty("researchObjects", out var r) ? r.EnumerateArray().Select(e => e.GetString()!).ToArray() : []))
            .ToList();
        return new Scope(lines, modules);
    }

    private static string Relative(string fullPath) => Path.GetRelativePath(Root, fullPath).Replace('\\', '/');

    /// <summary>The module that contains a repository-relative path: the longest declared path that is a prefix of it.</summary>
    private static Module? Owner(Scope scope, string relative) => scope.Modules
        .Where(m => string.Equals(relative, m.Path, StringComparison.Ordinal) || relative.StartsWith(m.Path + "/", StringComparison.Ordinal))
        .MaxBy(m => m.Path.Length);

    private static IEnumerable<string> ProjectFiles(string directory)
    {
        foreach (var file in Directory.EnumerateFiles(directory, "*.csproj"))
            yield return file;
        foreach (var sub in Directory.EnumerateDirectories(directory))
        {
            if (Skipped.Contains(Path.GetFileName(sub), StringComparer.Ordinal))
                continue;
            foreach (var file in ProjectFiles(sub))
                yield return file;
        }
    }

    [Fact]
    public void Every_declared_module_exists_on_a_known_line()
    {
        var scope = Load();
        foreach (var (line, mayReference) in scope.Lines)
            Assert.All(mayReference, target => Assert.True(scope.Lines.ContainsKey(target), $"line {line} may reference unknown line {target}"));
        Assert.Equal(scope.Modules.Count, scope.Modules.Select(m => m.Path).Distinct(StringComparer.Ordinal).Count());
        Assert.All(scope.Modules, m =>
        {
            Assert.True(scope.Lines.ContainsKey(m.Line), $"{m.Path}: unknown line {m.Line}");
            Assert.True(Directory.Exists(Path.Combine(Root, m.Path)), $"{m.Path}: declared but missing");
            Assert.All(m.ResearchObjects, o =>
            {
                Assert.StartsWith(m.Path + "/", o, StringComparison.Ordinal);
                Assert.True(File.Exists(Path.Combine(Root, o)) || Directory.Exists(Path.Combine(Root, o)), $"{o}: declared research object is missing");
            });
        });
    }

    [Fact]
    public void Every_module_directory_is_declared()
    {
        var scope = Load();
        var undeclared = ModuleParents
            .Select(parent => Path.Combine(Root, parent))
            .Where(Directory.Exists)
            .SelectMany(Directory.EnumerateDirectories)
            .Where(d => !Skipped.Contains(Path.GetFileName(d), StringComparer.Ordinal))
            .Select(Relative)
            .Where(relative => Owner(scope, relative) is null)
            .ToList();
        Assert.True(undeclared.Count == 0, "modules not declared in configs/project-scope.json: " + string.Join(", ", undeclared));
    }

    [Fact]
    public void Project_references_stay_within_the_lines_each_line_may_reference()
    {
        var scope = Load();
        var violations = new List<string>();
        foreach (var project in ModuleParents.Select(p => Path.Combine(Root, p)).Where(Directory.Exists).SelectMany(ProjectFiles))
        {
            var from = Owner(scope, Relative(project));
            Assert.True(from is not null, $"{Relative(project)} lies in no declared module");
            var references = XDocument.Load(project).Descendants()
                .Where(e => string.Equals(e.Name.LocalName, "ProjectReference", StringComparison.Ordinal))
                .Select(e => e.Attribute("Include")?.Value)
                .OfType<string>();
            foreach (var include in references)
            {
                var target = Relative(Path.GetFullPath(Path.Combine(Path.GetDirectoryName(project)!, include.Replace('\\', '/'))));
                var to = Owner(scope, target);
                if (to is null)
                    violations.Add($"{Relative(project)} -> {target} (undeclared)");
                else if (!scope.Lines[from.Line].Contains(to.Line, StringComparer.Ordinal))
                    violations.Add($"{from.Path} ({from.Line}) -> {to.Path} ({to.Line})");
            }
        }
        Assert.True(violations.Count == 0, "references across lines that the scope forbids: " + string.Join("; ", violations));
    }
}
