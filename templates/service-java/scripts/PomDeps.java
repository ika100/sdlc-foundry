// Platform-owned (spec 095): pins one Maven artifact in pom.xml. Run as `java scripts/PomDeps.java set <groupId>:<artifactId> <version>`.
// A text edit that keeps indentation and comments; it never touches <parent> or <properties>.
//  - a direct <dependency> with an explicit <version> gets the new version;
//  - anything else is upserted into the project's <dependencyManagement> (created when missing).
// JDK classes only.
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import javax.xml.parsers.DocumentBuilderFactory;

public class PomDeps {
    static final class El {
        String name;
        String path;
        int open;
        int openEnd;
        int close;
        int closeEnd;
    }

    static int tagEnd(String s, int lt) {
        char quote = 0;
        for (int i = lt + 1; i < s.length(); i++) {
            char c = s.charAt(i);
            if (quote != 0) {
                if (c == quote) {
                    quote = 0;
                }
            } else if (c == '"' || c == '\'') {
                quote = c;
            } else if (c == '>') {
                return i;
            }
        }
        throw new IllegalStateException("unterminated tag");
    }

    static int skipTo(String s, int from, String end) {
        int e = s.indexOf(end, from);
        if (e < 0) {
            throw new IllegalStateException("unterminated " + end);
        }
        return e + end.length();
    }

    static List<El> scan(String s) {
        List<El> all = new ArrayList<>();
        Deque<El> stack = new ArrayDeque<>();
        int i = 0;
        while (i < s.length()) {
            int lt = s.indexOf('<', i);
            if (lt < 0) {
                break;
            }
            if (s.startsWith("<!--", lt)) {
                i = skipTo(s, lt, "-->");
            } else if (s.startsWith("<![CDATA[", lt)) {
                i = skipTo(s, lt, "]]>");
            } else if (s.startsWith("<?", lt)) {
                i = skipTo(s, lt, "?>");
            } else if (s.startsWith("<!", lt)) {
                i = tagEnd(s, lt) + 1;
            } else if (s.startsWith("</", lt)) {
                int gt = tagEnd(s, lt);
                El el = stack.pollFirst();
                if (el == null) {
                    throw new IllegalStateException("unbalanced pom.xml");
                }
                el.close = lt;
                el.closeEnd = gt + 1;
                i = gt + 1;
            } else {
                int gt = tagEnd(s, lt);
                int p = lt + 1;
                while (p < gt && !Character.isWhitespace(s.charAt(p)) && s.charAt(p) != '/') {
                    p++;
                }
                El el = new El();
                el.name = s.substring(lt + 1, p);
                el.path = stack.isEmpty() ? el.name : stack.peekFirst().path + "/" + el.name;
                el.open = lt;
                el.openEnd = gt + 1;
                if (s.charAt(gt - 1) == '/') {
                    el.close = el.openEnd;
                    el.closeEnd = el.openEnd;
                } else {
                    stack.addFirst(el);
                }
                all.add(el);
                i = gt + 1;
            }
        }
        if (!stack.isEmpty()) {
            throw new IllegalStateException("unbalanced pom.xml");
        }
        return all;
    }

    static El child(List<El> els, El parent, String name) {
        for (El e : els) {
            if (e.path.equals(parent.path + "/" + name) && e.open > parent.open && e.closeEnd <= parent.closeEnd) {
                return e;
            }
        }
        return null;
    }

    static String text(String s, El e) {
        return e == null ? null : s.substring(e.openEnd, e.close).trim();
    }

    static El find(List<El> els, String path) {
        for (El e : els) {
            if (e.path.equals(path)) {
                return e;
            }
        }
        return null;
    }

    static El matching(List<El> els, String s, String path, String g, String a) {
        for (El d : els) {
            if (d.path.equals(path) && g.equals(text(s, child(els, d, "groupId"))) && a.equals(text(s, child(els, d, "artifactId")))) {
                return d;
            }
        }
        return null;
    }

    static int lineStart(String s, int at) {
        return s.lastIndexOf('\n', at - 1) + 1;
    }

    static String indentOf(String s, int at) {
        String prefix = s.substring(lineStart(s, at), at);
        return prefix.isBlank() ? prefix : null;
    }

    static String dependency(String ind, String unit, String nl, String g, String a, String ver) {
        return ind + "<dependency>" + nl
            + ind + unit + "<groupId>" + g + "</groupId>" + nl
            + ind + unit + "<artifactId>" + a + "</artifactId>" + nl
            + ind + unit + "<version>" + ver + "</version>" + nl
            + ind + "</dependency>" + nl;
    }

    static String set(String s, String g, String a, String ver) {
        String nl = s.contains("\r\n") ? "\r\n" : "\n";
        List<El> els = scan(s);
        El direct = matching(els, s, "project/dependencies/dependency", g, a);
        if (direct != null) {
            El v = child(els, direct, "version");
            if (v != null) {
                return s.substring(0, v.openEnd) + ver + s.substring(v.close);
            }
        }
        El managed = matching(els, s, "project/dependencyManagement/dependencies/dependency", g, a);
        if (managed != null) {
            El v = child(els, managed, "version");
            if (v != null) {
                return s.substring(0, v.openEnd) + ver + s.substring(v.close);
            }
            El art = child(els, managed, "artifactId");
            String ind = indentOf(s, art.open);
            return s.substring(0, art.closeEnd) + nl + (ind == null ? "" : ind) + "<version>" + ver + "</version>" + s.substring(art.closeEnd);
        }
        El mgmtDeps = find(els, "project/dependencyManagement/dependencies");
        if (mgmtDeps != null) {
            String closeInd = indentOf(s, mgmtDeps.close);
            El first = find(els, "project/dependencyManagement/dependencies/dependency");
            String firstInd = first == null ? null : indentOf(s, first.open);
            String base = closeInd == null ? "" : closeInd;
            String unit = firstInd != null && firstInd.startsWith(base) && firstInd.length() > base.length()
                ? firstInd.substring(base.length()) : "  ";
            String block = dependency(base + unit, unit, nl, g, a, ver);
            if (closeInd != null) {
                int at = lineStart(s, mgmtDeps.close);
                return s.substring(0, at) + block + s.substring(at);
            }
            return s.substring(0, mgmtDeps.close) + nl + block + s.substring(mgmtDeps.close);
        }
        El mgmt = find(els, "project/dependencyManagement");
        if (mgmt != null) {
            String closeInd = indentOf(s, mgmt.close);
            String base = closeInd == null ? "" : closeInd;
            String unit = "  ";
            String block = base + unit + "<dependencies>" + nl + dependency(base + unit + unit, unit, nl, g, a, ver) + base + unit + "</dependencies>" + nl;
            int at = closeInd != null ? lineStart(s, mgmt.close) : mgmt.close;
            return s.substring(0, at) + (closeInd != null ? "" : nl) + block + s.substring(at);
        }
        // no <dependencyManagement> at all: create it before the project's <dependencies>, else before </project>
        El deps = find(els, "project/dependencies");
        int pos = deps != null ? deps.open : find(els, "project").close;
        String lead = indentOf(s, pos);
        String ind = deps != null && lead != null ? lead : "  ";
        String unit = "  ";
        String block = ind + "<dependencyManagement>" + nl
            + ind + unit + "<dependencies>" + nl
            + dependency(ind + unit + unit, unit, nl, g, a, ver)
            + ind + unit + "</dependencies>" + nl
            + ind + "</dependencyManagement>" + nl;
        if (lead != null) {
            int at = lineStart(s, pos);
            return s.substring(0, at) + block + s.substring(at);
        }
        return s.substring(0, pos) + nl + block + s.substring(pos);
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3 || !args[0].equals("set") || !args[1].matches("[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+")
            || !args[2].matches("[A-Za-z0-9_.+-]+")) {
            System.err.println("usage: java scripts/PomDeps.java set <groupId>:<artifactId> <version>");
            System.exit(2);
        }
        String[] ga = args[1].split(":");
        Path pom = Path.of("pom.xml");
        String before = Files.readString(pom, StandardCharsets.UTF_8);
        String after = set(before, ga[0], ga[1], args[2]);
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        f.newDocumentBuilder().parse(new ByteArrayInputStream(after.getBytes(StandardCharsets.UTF_8)));
        Files.writeString(pom, after, StandardCharsets.UTF_8);
    }
}
