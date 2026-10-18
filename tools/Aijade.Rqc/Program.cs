using Aijade.Research.RqC;

// RQ-C 2×2 harness: dotnet run --project tools/Aijade.Rqc -- [--backend mock|ollama] [--model NAME] [...]; --help lists the flags.
if (args.Contains("--help") || args.Contains("-h"))
{
    Console.Out.Write(RqcRunner.HelpText);
    return 0;
}
try
{
    var cfg = RqcCliConfig.Parse(args);
    var (outDir, summary) = await RqcRunner.RunAsync(cfg, log: Console.Out);
    Console.Out.WriteLine($"runId={cfg.RunId} fingerprint={cfg.Fingerprint()} mode={summary["mode"]}");
    Console.Out.WriteLine($"degeneracy: {summary["degeneracy"]?["note"]}");
    Console.Out.WriteLine($"artifacts: {outDir}/{{trials.jsonl,summary.json}}");
    return 0;
}
catch (Exception e) when (e is ArgumentException or IOException or InvalidOperationException)
{
    Console.Error.WriteLine($"FATAL: {e.Message}");
    return 1;
}
