using System.Text.Json.Nodes;

using Aijade.Client.Api;

namespace Aijade.Client.Companion;

/// <summary>Her place on MOSAIC's stage, as the workbench reports it: whether the scene runs, where she is, and her posture.</summary>
public sealed record StageState(bool Running, string? Where, string? Posture)
{
    /// <summary>Sitting or lying, so that "get up" means something.</summary>
    public bool Seated => Posture is "sit" or "lie";

    /// <summary>Lying down: MOSAIC does not let her speak first then, and neither does AIJADE.</summary>
    public bool Lying => Posture == "lie";
}

/// <summary>
/// The chat's side of MOSAIC's stage (docs/STAGE-MOSAIC.md, plan A step 2): reads her state and sends one reply's commands
/// through the server, which relays them to MOSAIC's workbench on its own machine (<c>/api/v1/stage</c>, admins only).
/// </summary>
public sealed class MosaicStage(AijadeApi api)
{
    /// <summary>Her state, or null when the server has no stage, the account may not use it, or the workbench is not running.</summary>
    public async Task<StageState?> StateAsync(CancellationToken ct = default)
    {
        try
        {
            if (await api.SendAsync(HttpMethod.Get, "/api/v1/stage", ct: ct).ConfigureAwait(false) is not JsonObject r || r["running"]?.GetValue<bool>() != true)
                return null;
            return new StageState(true, r["where"]?.GetValue<string>(), r["posture"]?.GetValue<string>());
        }
        catch (AijadeApiException)
        {
            return null;
        }
    }

    /// <summary>Send one command line (<see cref="Stage.CommandLine"/>); a refusal comes back as <see cref="AijadeApiException"/>.</summary>
    public Task SendAsync(string commandLine, CancellationToken ct = default) =>
        api.SendAsync(HttpMethod.Post, "/api/v1/stage/command", new JsonObject { ["text"] = commandLine }, ct);
}
