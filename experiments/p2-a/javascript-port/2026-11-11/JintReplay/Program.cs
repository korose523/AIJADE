using System.Text.Json;

using Aijade.Research.SkillBench;

if (args.Length != 3)
    throw new ArgumentException("Provide the prepared task, runtime and port paths.");

var options = new JsonSerializerOptions(JsonSerializerDefaults.Web);
using var input = File.OpenRead(args[0]);
var task = JsonSerializer.Deserialize<ReplayInput>(input, options) ?? throw new InvalidDataException("Missing task.");
var benchTask = new BenchTask(task.TaskId, task.Statement, BenchCategory.Logic, BenchTier.Medium, task.Cases, 2000)
{
    PublicContract = task.Contract,
};
var code = File.ReadAllText(args[1]) + "\n" + File.ReadAllText(args[2]);
var result = new Sandbox().RunTask(code, benchTask);
Console.WriteLine(JsonSerializer.Serialize(new
{
    task.TaskId,
    result.Passed,
    result.Total,
    result.Error,
    result.DurationMs,
    failures = result.Failures.Select(failure => new
    {
        failure.Index,
        failure.Error,
        actual = Preview(failure.Actual),
    }),
}, options));

static string? Preview(string? value) => value?.Length > 180 ? value[..180] : value;

internal sealed record ReplayInput(string TaskId, string Statement, string Contract, BenchCase[] Cases);
