using Aijade.Memory.Model;

namespace Aijade.Memory.Dynamics;


public static class Gating
{
    private static double Clamp01(double x) => Math.Min(1, Math.Max(0, x));

    /// <summary>Durability multiplier: exactly 1 under NO_GATING; &gt; 1 for salient / social content otherwise.</summary>
    public static double Durability(ContentSalience s, GatingCoefficients g) =>
        1 + (g.KSalience * Clamp01(s.Salience)) + (g.KSocial * Clamp01(s.SocialSalience));

    /// <summary>Decay exponent driven by content salience; the base power law under NO_GATING.</summary>
    public static double DecayExponent(double salience, double baseDecay, GatingCoefficients g) =>
        baseDecay * (1 + (g.KSalience * (1 - Clamp01(salience))));
}

public static class Forgetting
{
    /// <summary>strength = baseStrength · durability · (1 + accessCount)^β / (1 + age/ageScale)^decay.</summary>
    public static double RetrievalStrength(
        double createdAt, int accessCount, double baseStrength, double durability,
        double now, ForgettingConfig f, GatingCoefficients g, double salience)
    {
        var ageNorm = Math.Max(0, now - createdAt) / f.AgeScaleMs;
        var decay = Math.Pow(1 + ageNorm, Gating.DecayExponent(salience, f.BaseDecay, g));
        var spacing = Math.Pow(1 + accessCount, f.SpacingBeta);
        return baseStrength * durability * spacing / decay;
    }
}

/// <summary>The bounded gate L3 exposes to memory and action. The neutral gate is the ablation control.</summary>
public sealed record PlasticityGate(
    double ConsolidationGain, double DecayMultiplier, double RetrievalNoise,
    double MoodCongruenceWeight, double SocialBonus, double ExplorationTemperature)
{
    public static PlasticityGate Neutral { get; } = new(1, 1, 0, 0, 1, 0);

    public PlasticityGate Clamped() => new(
        Math.Clamp(ConsolidationGain, 0.2, 3.0), Math.Clamp(DecayMultiplier, 0.5, 4.0), Math.Clamp(RetrievalNoise, 0.0, 0.3),
        Math.Clamp(MoodCongruenceWeight, 0.0, 1.0), Math.Clamp(SocialBonus, 1.0, 2.0), Math.Clamp(ExplorationTemperature, 0.0, 1.2));
}

/// <summary>Legacy L3 hormone state (deprecated as a memory gate; kept for audit and the lifecycle sweep).</summary>
public sealed record PhysiologicalState(double Dopamine, double Serotonin, double Cortisol, double Oxytocin, double Adrenaline, double? Intimacy = null);

public sealed record HormoneLevels(double Dopamine, double Serotonin, double Cortisol, double Oxytocin, double Adrenaline);

/// <summary>Three-layer hormone state: personality trait, slower mood, acute transient.</summary>
public sealed record PhysiologicalStateV3(HormoneLevels Trait, HormoneLevels Mood, HormoneLevels Transient, Affect Affect, double? Intimacy = null);

/// <summary>Expression-only modulation, all in [0, 1]: warmth, verbosity, hesitation (0 = neutral), energy.</summary>
public sealed record PresentationModulation(double Warmth, double Verbosity, double Hesitation, double Energy)
{
    public static PresentationModulation Neutral { get; } = new(0.5, 0.5, 0, 0.5);
}

public static class Plasticity
{
    private static double Clamp01(double x) => Math.Min(1, Math.Max(0, x));

    /// <summary>Content salience → gate. Neutral content gives exactly the neutral gate.</summary>
    public static PlasticityGate GateFromContent(ContentSalience sal, double surprise = 0.5)
    {
        var s = Clamp01(sal.Salience);
        var soc = Clamp01(sal.SocialSalience);
        var nov = Clamp01(sal.Novelty);
        return new PlasticityGate(
            1 + (2 * s * (0.5 + (0.5 * Clamp01(surprise)))), 1 - (0.5 * s), 0.3 * nov, soc, 1 + soc, 1.2 * nov).Clamped();
    }

    /// <summary>Whether a gate is the identity (asserts that the ablation control really is neutral).</summary>
    public static bool IsNeutral(PlasticityGate g)
    {
        var n = PlasticityGate.Neutral;
        return Math.Abs(g.ConsolidationGain - n.ConsolidationGain) < 1e-9 && Math.Abs(g.DecayMultiplier - n.DecayMultiplier) < 1e-9
            && Math.Abs(g.RetrievalNoise - n.RetrievalNoise) < 1e-9 && Math.Abs(g.MoodCongruenceWeight - n.MoodCongruenceWeight) < 1e-9
            && Math.Abs(g.SocialBonus - n.SocialBonus) < 1e-9 && Math.Abs(g.ExplorationTemperature - n.ExplorationTemperature) < 1e-9;
    }

    /// <summary>
    /// Legacy hormone state → gate, kept for compatibility and audit (two-stage forgetting). The store no longer uses it for
    /// memory gating: hormones were shown to contribute ≈ 0 to recall (H2c), so memory is gated by content salience.
    /// </summary>
    public static PlasticityGate GateFromState(PhysiologicalState state, double surprise = 0.5)
    {
        var salience = Clamp01(state.Dopamine) * (0.5 + (0.5 * Clamp01(surprise)));
        return new PlasticityGate(
            0.2 + (2.8 * salience), 0.5 + (3.5 * Clamp01(state.Cortisol)), 0.3 * Clamp01(state.Cortisol), Clamp01(state.Serotonin),
            1 + (Clamp01(state.Oxytocin) * Clamp01(state.Intimacy ?? 0)), 1.2 * Clamp01(state.Adrenaline)).Clamped();
    }

    /// <summary>
    /// Bridge from gating coefficients: all-zero content coefficients (NO_GATING) give exactly the neutral gate for any
    /// state, keeping the ablation control clean; otherwise the legacy state gate (audit / lifecycle only).
    /// </summary>
    public static PlasticityGate GateFromCoefficients(GatingCoefficients c, PhysiologicalState state) =>
        c.KSalience == 0 && c.KSocial == 0 && c.KNovelty == 0 ? PlasticityGate.Neutral : GateFromState(state);

    /// <summary>Hormones affect only how things are said; disabled → the neutral presentation, zero memory effect.</summary>
    public static PresentationModulation DerivePresentation(PhysiologicalStateV3 state, bool enabled)
    {
        if (!enabled)
            return PresentationModulation.Neutral;
        var (mood, transient) = (state.Mood, state.Transient);
        var warmth = 0.5 + (0.25 * (mood.Oxytocin + transient.Oxytocin - 1)) + (0.15 * (mood.Serotonin - 0.5));
        var verbosity = 0.5 + (0.30 * (mood.Dopamine - 0.5)) + (0.20 * (transient.Adrenaline - 0.5));
        var hesitation = (0.40 * (mood.Cortisol - 0.5)) + (0.30 * (transient.Cortisol - 0.5));
        var energy = 0.5 + (0.25 * (transient.Adrenaline - 0.5)) + (0.15 * (mood.Dopamine - 0.5));
        return new PresentationModulation(Clamp01(warmth), Clamp01(verbosity), Clamp01(hesitation), Clamp01(energy));
    }

    /// <summary>Deterministic FNV-1a hash of a key mapped to [0, 1) — retrieval noise must be reproducible.</summary>
    public static double DeterministicUnit(string key)
    {
        unchecked
        {
            var h = 0x811C9DC5u;
            foreach (var c in key)
            {
                h ^= c;
                h *= 0x01000193u;
            }
            return h / 4294967296.0;
        }
    }

    /// <summary>score · (1 − noise · u(key)); noise ≤ 0.3, and the same memory always loses the same share.</summary>
    public static double ApplyRetrievalNoise(double score, string key, double noise) =>
        noise <= 0 ? score : score * (1 - (noise * DeterministicUnit(key)));
}
