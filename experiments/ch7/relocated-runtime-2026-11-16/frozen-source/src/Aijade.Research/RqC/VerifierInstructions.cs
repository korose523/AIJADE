namespace Aijade.Research.RqC;

/// <summary>Instruction intent is explicit and versioned; the historical builders keep their original bytes.</summary>
public static class VerifierInstructions
{
    public const string Legacy = "listed-v1";
    public const string WholeTask = "whole-task-v2";
    public const string WholeTaskCriterion = "Judge the complete stated task, including valid inputs not displayed here. PASS means the code satisfies the full specification; FAIL means it does not. Passing only the displayed examples is insufficient.";

    public static void Validate(string version)
    {
        if (version is not (Legacy or WholeTask))
            throw new ArgumentException("Unknown verifier instruction version.", nameof(version));
    }
}
