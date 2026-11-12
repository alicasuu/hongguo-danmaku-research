import java.net.SocketPermission;
import java.security.Permission;

/** JDK 17–23 runtime guard; fail closed if the network guard cannot be installed. */
@SuppressWarnings("removal")
public final class OfflineLauncher {
    public static void main(String[] args) throws Exception {
        System.setSecurityManager(new SecurityManager() {
            @Override public void checkPermission(Permission permission) {
                if (permission instanceof SocketPermission)
                    throw new SecurityException("Network disabled in offline proof of concept");
                if (permission instanceof RuntimePermission && permission.getName().equals("setSecurityManager"))
                    throw new SecurityException("Offline guard cannot be removed");
            }
            @Override public void checkExec(String command) {
                throw new SecurityException("Subprocesses disabled inside offline JVM");
            }
        });
        if (args.length == 1 && args[0].equals("guard-check")) {
            try {
                System.getSecurityManager().checkConnect("127.0.0.1", 9);
                throw new AssertionError("Network guard failed");
            } catch (SecurityException expected) {
                System.out.println("{\"network_guard_blocked\":true}");
            }
        } else if (args.length == 1 && args[0].equals("test")) {
            org.junit.runner.JUnitCore.main("com.hgtv.star.core.SignerTest", "com.hgtv.star.core.DanmakuTest");
        } else if (args.length == 1 && args[0].equals("bridge")) {
            Class.forName("com.hgtv.star.core.BridgeKt").getMethod("main").invoke(null);
        } else {
            throw new IllegalArgumentException("Use test, guard-check, or bridge");
        }
    }
}
