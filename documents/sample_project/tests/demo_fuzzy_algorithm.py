"""
Live Fuzzy Matching Algorithm Demonstration
=========================================== 
Shows how the UPDATED algorithm handles special characters AND multiple matches.
"""
import re

def normalize_string(s):
    """Remove spaces, hyphens, underscores, and dots for comparison."""
    return re.sub(r'[\s\-_\.]', '', s.lower().strip())

def calculate_similarity(str1, str2):
    """Calculate similarity between two strings using Levenshtein distance with normalization."""
    s1, s2 = str1.lower().strip(), str2.lower().strip()
    
    # Exact match
    if s1 == s2:
        return 1.0, "exact"
    
    # Normalized comparison (handles "CR V" vs "CR-V" vs "CRV")
    n1, n2 = normalize_string(str1), normalize_string(str2)
    if n1 == n2:
        return 0.98, "normalized"  # Near-perfect match after normalization
    
    # Check if normalized versions contain each other
    if n1 in n2 or n2 in n1:
        return 0.92, "normalized_contains"
    
    # Check if one contains the other (original)
    if s1 in s2 or s2 in s1:
        return 0.9, "contains"
    
    # Calculate similarity for both original and normalized
    original_score = levenshtein_similarity(s1, s2)
    normalized_score = levenshtein_similarity(n1, n2)
    
    if normalized_score > original_score:
        return normalized_score, "levenshtein_normalized"
    return original_score, "levenshtein_original"

def levenshtein_similarity(str1, str2):
    """Calculate similarity based on Levenshtein distance."""
    longer = str1 if len(str1) > len(str2) else str2
    shorter = str2 if len(str1) > len(str2) else str1
    
    if len(longer) == 0:
        return 1.0
    
    distance = levenshtein_distance(longer, shorter)
    return (len(longer) - distance) / len(longer)

def levenshtein_distance(str1, str2):
    """Calculate Levenshtein distance between two strings."""
    matrix = [[0] * (len(str1) + 1) for _ in range(len(str2) + 1)]
    
    for i in range(len(str1) + 1):
        matrix[0][i] = i
    for j in range(len(str2) + 1):
        matrix[j][0] = j
    
    for j in range(1, len(str2) + 1):
        for i in range(1, len(str1) + 1):
            cost = 0 if str1[i-1] == str2[j-1] else 1
            matrix[j][i] = min(
                matrix[j][i-1] + 1,
                matrix[j-1][i] + 1,
                matrix[j-1][i-1] + cost
            )
    
    return matrix[len(str2)][len(str1)]

def test_multiple_matches():
    """Demonstrate how multiple matches are handled."""
    
    print("\n" + "=" * 90)
    print("⚠️ MULTIPLE MATCH SCENARIO: What happens with 'CR V'?")
    print("=" * 90)
    
    # Simulating your actual dropdown options
    dropdown_options = [
        ("CRV", "10325"),      # First option
        ("CR-V", "268"),       # Second option - same normalized value!
    ]
    
    search_value = "CR V"
    print(f"\n🔍 Searching for: '{search_value}'")
    print(f"   Normalized: '{normalize_string(search_value)}'")
    print("-" * 70)
    
    all_matches = []
    for option_text, option_value in dropdown_options:
        score, match_type = calculate_similarity(search_value, option_text)
        all_matches.append({
            'text': option_text,
            'value': option_value,
            'score': score,
            'match_type': match_type,
            'length_diff': abs(len(option_text) - len(search_value)),
            'normalized': normalize_string(option_text)
        })
    
    print(f"\n{'Option':<10} {'Normalized':<12} {'Score':<8} {'Len Diff':<10} {'Match Type'}")
    print("-" * 70)
    
    for m in all_matches:
        print(f"{m['text']:<10} {m['normalized']:<12} {m['score']*100:>5.1f}%  {m['length_diff']:<10} {m['match_type']}")
    
    # Sort by: score (desc), length_diff (asc), text length (asc)
    all_matches.sort(key=lambda x: (-x['score'], x['length_diff'], len(x['text'])))
    
    print("\n📊 SELECTION PRIORITY (after sorting):")
    print("-" * 70)
    for i, m in enumerate(all_matches):
        priority = "🥇 SELECTED (Best match)" if i == 0 else "🥈 Alternative (logged in warning)"
        print(f"   {i+1}. {m['text']:<10} Score: {m['score']*100:.1f}%  Length Diff: {m['length_diff']}  → {priority}")
    
    winner = all_matches[0]
    alternatives = [m for m in all_matches[1:] if abs(m['score'] - winner['score']) <= 0.02]
    
    print("\n" + "=" * 90)
    print("📋 SELECTION LOGIC WHEN MULTIPLE MATCHES HAVE SAME SCORE:")
    print("=" * 90)
    print("""
    Priority Order:
    ───────────────
    1️⃣  Highest similarity score (must be within 1% to be considered equal)
    2️⃣  Closest length to original input (smaller length difference wins)
    3️⃣  Shorter option text preferred (simpler name = more likely correct)
    4️⃣  First occurrence in dropdown (final tie-breaker)
    
    In this case:
    ─────────────
    • "CRV" has length_diff = |3 - 4| = 1  (search "CR V" is 4 chars)
    • "CR-V" has length_diff = |4 - 4| = 0  ← Closer match!
    
    So "CR-V" should be selected because it's closer in length to "CR V"
    """)
    
    print("⚠️ LOG OUTPUT WHEN MULTIPLE MATCHES DETECTED:")
    print("-" * 70)
    print(f'   🔍 FUZZY MATCH for Vehicle.Model: "CR V" → "{winner["text"]}" ({winner["score"]*100:.1f}% similarity)')
    if alternatives:
        alt_str = ", ".join([f'"{m["text"]}" ({m["score"]*100:.0f}%)' for m in [winner] + alternatives])
        print(f'   ⚠️ MULTIPLE MATCHES: Found {alt_str}. Selected: "{winner["text"]}"')
    
    print("\n📧 EMAIL NOTIFICATION FORMAT:")
    print("-" * 70)
    print(f'   Automatic corrections applied: Vehicle.Model ({winner["score"]*100:.0f}%)')
    if alternatives:
        print(f'   ⚠️ Note: Multiple similar options found ({len(alternatives)+1} matches)')

def test_fuzzy_matching():
    """Main test function."""
    print("\n🔍 FUZZY MATCHING - MULTIPLE MATCH HANDLING")
    print("=" * 90)
    
    test_multiple_matches()
    
    print("\n" + "=" * 90)
    print("🎯 SUMMARY: What Happens with Multiple Matches?")
    print("=" * 90)
    print("""
    ✅ All matches above 60% threshold are collected
    ✅ Matches are sorted by: score → length similarity → text length
    ✅ Best match is selected automatically
    ✅ Warning is logged if multiple matches within 2% of best score
    ✅ Email includes note about multiple matches found
    ✅ User can see alternatives in logs for troubleshooting
    """)

if __name__ == "__main__":
    test_fuzzy_matching()