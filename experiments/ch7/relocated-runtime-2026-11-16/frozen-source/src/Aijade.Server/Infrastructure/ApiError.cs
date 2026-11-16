using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Server.V9;

namespace Aijade.Server.Infrastructure;

/// <summary>An expected, client-visible failure: an HTTP status, a stable error code and a message (plus optional issues).</summary>
public sealed class ApiException(int status, string code, string message, IReadOnlyList<BoundaryIssue>? issues = null) : Exception(message)
{
    public int Status { get; } = status;

    public string Code { get; } = code;

    public IReadOnlyList<BoundaryIssue>? Issues { get; } = issues;

    public static ApiException BadRequest(string message, string code, IReadOnlyList<BoundaryIssue>? issues = null) => new(400, code, message, issues);

    public static ApiException Unauthorized() => new(401, "UNAUTHORIZED", "Unauthorized");

    public static ApiException Forbidden(string message = "Forbidden") => new(403, "FORBIDDEN", message);

    public static ApiException NotFound(string message = "Not found") => new(404, "NOT_FOUND", message);
}

/// <summary>Maps <see cref="ApiException"/> to its JSON body and any other failure to an opaque 500 (internal details stay in the log).</summary>
public sealed class ApiErrorMiddleware(RequestDelegate next, ILogger<ApiErrorMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await next(context).ConfigureAwait(false);
        }
        catch (ApiException e) when (!context.Response.HasStarted)
        {
            await WriteAsync(context, e.Status, e.Code, e.Message, e.Issues).ConfigureAwait(false);
        }
        catch (BadHttpRequestException e) when (!context.Response.HasStarted)
        {
            await WriteAsync(context, 400, "BAD_REQUEST", e.Message, null).ConfigureAwait(false);
        }
        catch (Exception e) when (!context.Response.HasStarted && e is not OperationCanceledException)
        {
            logger.LogError(e, "unhandled error on {Method} {Path}", context.Request.Method, context.Request.Path);
            await WriteAsync(context, 500, "INTERNAL_SERVER_ERROR", "Internal Server Error", null).ConfigureAwait(false);
        }
    }

    public static Task WriteAsync(HttpContext context, int status, string code, string message, IReadOnlyList<BoundaryIssue>? issues)
    {
        context.Response.StatusCode = status;
        var body = new JsonObject { ["error"] = code, ["message"] = message };
        if (issues is { Count: > 0 })
            body["issues"] = new JsonArray([.. issues.Select(i => (JsonNode)new JsonObject { ["path"] = i.Path, ["message"] = i.Message })]);
        return context.Response.WriteAsJsonAsync(body, JsonSerializerOptions.Web);
    }
}
