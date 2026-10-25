import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

/**
 * Platform-owned (spec 091): prints the result lines of `devbox run smoke` from the surefire XML
 * reports in a directory: one `PASS|FAIL|SKIP  <path>::<method>` line per test, then
 * `smoke: <p> passed, <f> failed, <s> skipped`, or `0 smoke tests`.
 * Run: java scripts/SmokeSummary.java target/surefire-reports
 */
public class SmokeSummary {

  public static void main(String[] args) throws Exception {
    File dir = new File(args.length > 0 ? args[0] : "target/surefire-reports");
    File[] found = dir.listFiles((d, name) -> name.startsWith("TEST-") && name.endsWith(".xml"));
    if (found == null) {
      found = new File[0];
    }
    List<File> reports = new ArrayList<>(Arrays.asList(found));
    reports.sort(Comparator.comparing(File::getName));
    List<String> lines = new ArrayList<>();
    int passed = 0;
    int failed = 0;
    int skipped = 0;
    for (File report : reports) {
      var factory = DocumentBuilderFactory.newInstance();
      factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
      NodeList cases = factory.newDocumentBuilder().parse(report).getElementsByTagName("testcase");
      for (int i = 0; i < cases.getLength(); i++) {
        Element test = (Element) cases.item(i);
        String type = test.getAttribute("classname").split("\\$")[0];
        String name = test.getAttribute("name").replaceAll("\\(.*\\)$", "");
        String id = "src/test/java/" + type.replace('.', '/') + ".java::" + name;
        String result = "PASS";
        if (test.getElementsByTagName("failure").getLength() > 0
            || test.getElementsByTagName("error").getLength() > 0) {
          result = "FAIL";
          failed++;
        } else if (test.getElementsByTagName("skipped").getLength() > 0) {
          result = "SKIP";
          skipped++;
        } else {
          passed++;
        }
        lines.add(result + "  " + id);
      }
    }
    if (lines.isEmpty()) {
      System.out.println("0 smoke tests");
      return;
    }
    lines.forEach(System.out::println);
    System.out.println(
        "smoke: " + passed + " passed, " + failed + " failed, " + skipped + " skipped");
  }
}
