using Aijade.Server;

var app = AijadeServer.Build(args);
await AijadeServer.PrepareAsync(app).ConfigureAwait(false);
await app.RunAsync().ConfigureAwait(false);

/// <summary>Entry point type (also used by the test host).</summary>
public partial class Program;
