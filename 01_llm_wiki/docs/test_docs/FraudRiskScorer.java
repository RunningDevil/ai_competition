import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public class FraudRiskScorer {
    static class Transaction {
        final String id;
        final int amount;
        final int deviceAgeDays;
        final int failedLogins;
        final boolean crossBorder;
        final boolean trustedMerchant;

        Transaction(String id, int amount, int deviceAgeDays, int failedLogins,
                    boolean crossBorder, boolean trustedMerchant) {
            this.id = id;
            this.amount = amount;
            this.deviceAgeDays = deviceAgeDays;
            this.failedLogins = failedLogins;
            this.crossBorder = crossBorder;
            this.trustedMerchant = trustedMerchant;
        }
    }

    static int score(Transaction tx) {
        int score = 12;
        score += Math.min(35, tx.amount / 200);
        score += tx.deviceAgeDays < 7 ? 28 : tx.deviceAgeDays < 30 ? 14 : 0;
        score += Math.min(24, tx.failedLogins * 6);
        score += tx.crossBorder ? 18 : 0;
        score -= tx.trustedMerchant ? 15 : 0;
        return Math.max(0, Math.min(100, score));
    }

    static String decision(int score) {
        if (score >= 70) {
            return "REVIEW";
        }
        if (score >= 45) {
            return "STEP_UP";
        }
        return "PASS";
    }

    public static void main(String[] args) {
        List<Transaction> transactions = List.of(
                new Transaction("TX-9001", 8300, 3, 2, true, false),
                new Transaction("TX-9002", 1200, 180, 0, false, true),
                new Transaction("TX-9003", 4600, 21, 5, false, false),
                new Transaction("TX-9004", 2200, 5, 1, false, true)
        );
        List<String> rows = new ArrayList<>();
        for (Transaction tx : transactions) {
            int score = score(tx);
            rows.add(tx.id + "|" + score + "|" + decision(score));
        }
        rows.stream().sorted(Comparator.naturalOrder()).forEach(System.out::println);
    }
}
