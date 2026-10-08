use minisign_verify::{PublicKey, Signature};
fn main() {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let result = (|| -> Result<(), Box<dyn std::error::Error>> {
        if args.len() != 3 { return Err("Expected ARTIFACT PUBLIC_KEY SIGNATURE".into()); }
        let key = PublicKey::from_file(std::path::Path::new(&args[1]))?;
        let sig = Signature::from_file(std::path::Path::new(&args[2]))?;
        key.verify(&std::fs::read(&args[0])?, &sig, false)?;
        Ok(())
    })();
    if let Err(e) = result { eprintln!("Signature verification failed: {e}"); std::process::exit(2); }
    println!("PASS cryptographic updater signature verification");
}
